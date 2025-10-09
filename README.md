# FindMy

Query Apple's Find My network, allowing none Apple devices to retrieve the location reports.

This project based on all the hard work of, and is a combination of the following projects:

1. https://github.com/seemoo-lab/openhaystack/
2. https://github.com/biemster/FindMy
3. https://github.com/Dadoum/anisette-v3-server
4. https://github.com/mrmay-dev/owntags



## Installation and Setup for Web Service

📺 Installation and Walkthrough Video: https://youtu.be/yC2HIPDSxlM

This project only need a free Apple ID with SMS 2FA properly setup. If you don't have any, follow one of the many 
guides found on the internet. 

**Using your personal Apple ID is strongly discouraged. You are recommended to create a blank Apple ID for experimental purpose.**  If you ran into issue of "KeyError service-data", especially you are using an existing account rather than a new account, you may want to refer to https://github.com/Chapoly1305/FindMy/issues/9 .


🌐 A final result will be exactly like this website: https://findmy.chapoly1305[dot]com/docs

**Note:** You can use this website for testing purposes, but it operates on a extremely suspiciously low cost. VPS I could afford, so I cannot guarantee the security of your data or its availability. 

### Steps

1. Install [docker](https://docs.docker.com/engine/install/ubuntu/) and Python3-pip. Python3-venv is also strongly recommended.

2. The anisetter service shall run on the same device of this project. We use docker [image](https://hub.docker.com/r/dadoum/anisette-v3-server/tags) deployment.
   Here is the example command for Linux. If the system rebooted, this docker service will automatically start after reboot.

```bash
docker run -d --restart always --name anisette-v3 -p 6969:6969 dadoum/anisette-v3-server:latest
```

If docker is not applicable, you may setup [manually](https://github.com/Dadoum/anisette-v3-server). 

3. After deployed `anisette-v3-server`, you may validate the service is running by sending a `curl` request:

```bash
curl -I http://localhost:6969
```

You will receive a response like below. 

```json
{
  "X-Apple-I-Client-Time": "...",
  "X-Apple-I-MD": "...",
  "X-Apple-I-MD-LU": "...",
  "X-Apple-I-MD-M": "...",
  "X-Apple-I-MD-RINFO": "...",
  "X-Apple-I-SRL-NO": "0",
  "X-Apple-I-TimeZone": "UTC",
  "X-Apple-Locale": "en_US",
  "X-MMe-Client-Info": "<MacBookPro13,2> <macOS;13.1;22C65> <com.apple.AuthKit/1 (com.apple.dt.Xcode/3594.4.19)>",
  "X-Mme-Device-Id": "..."
}
```

4. Then, clone this repository, Navigate to `FindMy` directory, and deploy thorough interactive method by install the required python packages, or use Docker:

## Interactive Deployment (easier for debugging)
```bash
git clone https://github.com/Chapoly1305/FindMy.git
cd FindMy

# Optionally create and use the virtual environment
python3 -m venv venv
source venv/bin/activate

pip3 install -r requirements.txt

# Start the Web Service.
python3 web_service.py
```

**Hint:** This web service will die if the shell exited or system reboot. You could use `nohup`, `screen`, or set up a systemd service to keep it alive.

## Docker Deployment

If you prefer to run the web service in a Docker container, you can use the provided Dockerfile.

### Building the Docker Image

```bash
docker build -t findmy-service .
```

### Running the Container

**Important:** You need to pass your Apple ID credentials as environment variables when running the container to avoid interactive prompts:
Again, using your personal Apple ID is strongly discouraged. Create a separate Apple ID for this service.

```bash
docker run -d \
  --name findmy \
  --restart always \
  -e FINDMY_ACCOUNT="your-apple-id@example.com" \
  -e FINDMY_PASS="your-password" \
  -p 8000:8000 \
  --network host \
  findmy-service
```

**Note:**
- `--network host` is used to allow the container to access the anisette-v3-server running on localhost:6969
- Make sure the anisette-v3-server is running before starting this container
- Using `--restart always` ensures the container automatically restarts after system reboot

### Environment Variables

- `FINDMY_ACCOUNT`: Your Apple ID email address
- `FINDMY_PASS`: Your Apple ID password


## API Usage

The APIs are created with FastAPI, the documentations are written inline and can be accessed on website path http://127.0.0.1:8000/docs or http://127.0.0.1:8000/redoc. 




## Traditional Key File Method

### Using the Key Generation Tool

The `generate_keys.py` script creates the cryptographic keys needed for device tracking. Here's how to use it:

**Basic Key Generation**
```bash
# Generate a single key pair
python3 generate_keys.py

# Generate multiple key pairs
python3 generate_keys.py -n 5

# Add a prefix to key files
python3 generate_keys.py -p mydevice

# Command Line Options
# -n, --nkeys: Number of key pairs to generate (default: 1)
# -p, --prefix: Prefix for the generated key files
# -y, --yaml: Generate a YAML file containing the list of keys
# -v, --verbose: Print keys as they are generated
```


**Understanding the Generated Keys**
Each `.keys` file contains three components:
1. Private Key: Keep this secret! Used for decrypting location reports
2. Advertisement Key: Used for broadcasting BLE messages
3. Hashed Advertisement Key: Used for requesting location reports from Apple

The keys are stored in the `keys/` directory with filenames based on their hashed values.



### Advertise with Improved HCI.py on Linux

The OpenHayStack HCI.py has limitations when modifying Bluetooth adapter public addresses, as not all adapters support this functionality. The original HCI.py only works with specific Broadcom chips used in Raspberry Pi by alternating adapter public address. Since iOS 18.2, **iPhones and iPads only accept advertisements from random static addresses**. We've developed an improved version that sends advertisement with correct address type. As the original version, **Root Privilege Required.** 

```bash
usage: hci.py [-h] (--hex HEX | --base64 BASE64) [--instance INSTANCE] [--adapter ADAPTER]

    Bluetooth Low Energy Advertising Script
    
    Basic Usage:
        sudo python3 hci.py --hex <56_CHAR_HEX>
        sudo python3 hci.py --base64 <BASE64_STRING>
    
    Example with specific adapter and instance:
        sudo python3 hci.py --hex 7779d8492fc611545b472501f00dc131b04201ecf9d91431a8f88a75 --adapter hci0 --instance 05
        sudo python3 hci.py --base64 d3nYSS/GEVRbRyUB8A3BMbBCAez52RQxqPiKdQ== --adapter hci0 --instance 05
    
    Required Arguments (choose one):
        --hex        56-character hexadecimal string (28 bytes)
                    Example: 7779d8492fc611545b472501f00dc131b04201ecf9d91431a8f88a75
        --base64    Base64 encoded string (decodes to 28 bytes)
                    Example: d3nYSS/GEVRbRyUB8A3BMbBCAez52RQxqPiKdQ==
    
    Optional Arguments:
        --instance      Advertisement instance index (default: "05")
                        Different adapters support different quantities
        --adapter      Bluetooth adapter name (default: "hci0")
    

```

**Here is the explanation how it works.**

The adapter on Linux generally supports HCI command, defined in Bluetooth specification. The script use the `hcitool` to directly configure the address and send BLE advertisement. The advertisement is sent using random static address, instead of public address. This is critically important because the OpenHayStack method of using public address will slowly lossing coverage when Apple deploying mitigation on iOS 18.2. 



### Advertise and Track without Root Privileges

Our recent research shows the device maybe tracked without using root privileges. Our discovery will be published on **USENIX Security 2025**! 
As usual, our research is open-sourced, you can find it at [nRootTag](https://nroottag.github.io/).



### Requesting Location Reports

The `request_reports.py` script fetches location data for your tracked devices from Apple's servers.

**Basic Usage**
```bash
# Request reports for all keys in the keys directory
python3 request_reports.py

# Request reports for specific time period
python3 request_reports.py -H 48  # Last 48 hours

# Request reports for keys with specific prefix
python3 request_reports.py -p mydevice

#Command Line Options
# -H, --hours: Only show reports newer than specified hours (default: 24)
# -p, --prefix: Only use keyfiles starting with this prefix
# -r, --regen: Regenerate search-party-token
# -t, --trusteddevice: Use trusted device for 2FA instead of SMS
```



## Additional Information

### anisette-v3-server

Q: What does this external project do? The SMS code is only asked once, in where and how is the information stored?

A: Anisette is similar to a device fingerprint. It is intended to be stored on an Apple device once it becomes trusted. 
Subsequent requests made by this "device" using this fingerprint and same Apple account will not trigger the 2FA again. 
The first call (icloud_login_mobileme) is used to obtain the search party token. The subsequent calls 
(generate_anisette_headers) use the cached search party token from the first call as the password and the dsid as the 
username. I (@biemster) have observed that the search party tokens change when using different sources for anisette data,
possibly due to various reasons. If it's deployed as a docker container, the storage location is $HOME/.config/anisette-v3/
adi.pb and device.json. These numbers together generate a validation code like OTP, which then undergoes a process of 
Mixed Boolean Arithmetic to produce two anisette headers for the request. One header represents a relatively static 
machine serial, while the other header contains a frequently changing OTP. 
If you switch to https://github.com/Dadoum/pyprovision, you will obtain the ADI data in the anisette folder. 
(Answer revised and organized from https://github.com/biemster/FindMy/issues/37#issuecomment-1840277808)
