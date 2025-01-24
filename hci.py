import argparse
import base64
import subprocess
import time
import re
from cryptography.hazmat.primitives import hashes
import requests


def validate_hex_input(hex_string: str) -> bool:
    """
    Validate that the input string is a valid 56-character hexadecimal string.
    Returns True if valid, False otherwise.
    """
    if len(hex_string) != 56:
        return False
    return bool(re.match(r'^[0-9a-fA-F]{56}$', hex_string))


class Payload:
    def __init__(self, public_key: str, adapter_name: str, instance: str):
        # public_key hex to bytes
        self.adapter_name = adapter_name
        self.public_key = bytes.fromhex(public_key)
        self.addr = self.public_key[:6]
        self.pub0_bits = "".join([f"{self.public_key[0] >> 6:02X}"])
        self.instance = instance
        self.addr_type = None

    def get_addr(self):
        return [f"{byte:02X}" for byte in self.addr]

    def get_pubkey_part2(self):
        return [f"{byte:02X}" for byte in self.public_key[6:28]]

    def get_addr_reverse(self):
        # Create a list from the address bytes
        addr_bytes = list(self.addr)
        
        # Modify the first byte to ensure the two MSBs are 1
        # We use 0xC0 (11000000 in binary) with OR operation to set top 2 bits
        # while preserving the other 6 bits
        addr_bytes[0] = addr_bytes[0] | 0xC0
        
        # Convert to hex strings and reverse
        return [f"{byte:02X}" for byte in addr_bytes[::-1]]

    def reset_adapter(self, adapter_name):
        self._run_command(["hciconfig", adapter_name, "reset"])

    # Some older adater does not support 0x0035, you will need to reference
    # the BT 4.0 Spec and use other commands
    def ble5_set_random_static_addr(self):
        # hcitool -i hci1 cmd 0x08 0x0035 01 02 00 00 05 05 30
        self._run_command(["hcitool", "-i", self.adapter_name, "cmd",
                           "0x08", "0x0035",
                           self.instance] +  # Advertise Handle
                          self.get_addr_reverse())
        self.addr_type = "random"

    # Some older adater does not support 0x0035, you will need to reference
    # the BT 4.0 Spec and use other commands
    def set_public_addr(self):
        # This only works for some adapters, require root permission and driver support
        # Tested on Intel AX200 series
        self._run_command(["btmgmt", "-i", self.adapter_name, "power", "off"])
        time.sleep(0.5)
        self._run_command(["btmgmt", "-i", self.adapter_name, "public-addr",
                           ":".join(self.get_addr())])
        time.sleep(0.5)
        self._run_command(["btmgmt", "-i", self.adapter_name, "power", "on"])
        self.addr_type = "public"

    def ble5_set_parameters_extended(self):
        if self.addr_type is None:
            print("Please set the address type (public/random) first")
            exit(1)

        # hcitool -i hci1 cmd 0x08 0x0036 01 13 00 A0 00 00 B0 00 00 07 01 01 00 00 00 00 00 00 00 7F 01 01 01 00 00
        self._run_command(["hcitool", "-i", self.adapter_name, "cmd",
                           "0x08", "0x0036",
                           self.instance,  # Advertising_Handle
                           "13", "00",  # Advertising_Event_Properties
                           "00", "00", "50",  # Primary_Advertising_Interval_Min
                           "00", "00", "70",  # Primary_Advertising_Interval_Max
                           "07",  # Primary_Advertising_Channel_Map
                           "01" if self.addr_type == "random" else "00",  # Own_Address_Type
                           "01",  # Peer_Address_Type
                           "00", "00", "00", "00", "00", "00",  # Peer_Address
                           "00",  # Advertising_Filter_Policy
                           "7F",  # Advertising_TX_Power
                           "01",  # Primary_Advertising_PHY
                           "01",  # Secondary_Advertising_Max_Skip
                           "01",  # Secondary_Advertising_PHY
                           "00",  # Advertising_SID
                           "00"  # Scan_Request_Notification_Enable
                           ])

    def ble5_set_advertising_data(self):
        # hcitool -i hci1 cmd 0x08 0x0037 01 03 01 1F 1e ff 4c 00 12 19 00 [Part Two]
        self._run_command(["hcitool", "-i", self.adapter_name, "cmd",
                           "0x08", "0x0037",
                           self.instance,  # Advertise Handle
                           "03", "01", "1F",
                           "1E", "FF", "4C", "00", "12", "19", "00"] +
                          self.get_pubkey_part2() +
                          [self.pub0_bits,
                           "00"])  # Hint. But doesn't really matter

    def ble5_start_advertising(self):
        # hcitool -i hci1 cmd 0x08 0x0039 01 01 01 00 00 00
        self._run_command(["hcitool", "-i", self.adapter_name, "cmd",
                           "0x08", "0x0039",
                           "01",  # 01 for Enable, 00 for Disable
                           "01",
                           self.instance,  # Advertise Handle
                           "00", "00", "00"])

    def stop_advertising(self):
        # hcitool -i hci1 cmd 0x08 0x000a 01
        self._run_command(["hcitool", "-i", self.adapter_name, "cmd",
                           "0x08", "0x0039",
                           "00",  # 01 for Enable, 00 for Disable
                           "01",
                           self.instance,  # Advertise Handle
                           "00", "00", "00"])

    def _run_command(self, command):
        for i in command:
            print(i, end=" ")
        print()
        subprocess.run(command)


def main():
    parser = argparse.ArgumentParser(description="BLE advertising script with hex input")

    # Add input group for mutually exclusive hex
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--hex", help="56-character hexadecimal string (28 bytes)")

    parser.add_argument("--adv_method",
                        choices=["traditional", "extended"],
                        default="extended",
                        help="Choose the advertising method (extended)"
                             "\ntraditional: Use the traditional advertising method e.g., OCF 0x0006, 0x0008, 0x000a"
                             "\nextended: Use the BLE5.0 extended advertising method e.g., OCF 0x0036, 0x0037, 0x0039")

    parser.add_argument("--instance", help="Advertisement instance index. (05)", default="05")
    parser.add_argument("--adapter", '-d', help="Bluetooth adapter name. (hci0)", default="hci0")

    args = parser.parse_args()

    # Validate and process input
    if args.hex:
        if not validate_hex_input(args.hex):
            print("Error: Invalid hex input. Must be exactly 56 hexadecimal characters (0-9, a-f, A-F)")
            return
        input_hex = args.hex

    # Create payload and start advertising
    msg = Payload(input_hex, args.adapter, args.instance)

    # Set address type
    msg.ble5_set_random_static_addr()

    # Configure and start advertising
    if args.adv_method == "traditional":
        print("Using traditional advertising method is not yet implemented.")
    else:
        print("Using BLE5.0 extended advertising method")
        msg.ble5_set_parameters_extended()
        msg.ble5_set_advertising_data()
        msg.ble5_start_advertising()

    print("Advertising started. Press Ctrl+C to stop...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping advertisement...")
        msg.stop_advertising()
        print("Advertisement stopped.")


if __name__ == "__main__":
    main()