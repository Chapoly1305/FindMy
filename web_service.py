# /* Integration of Find My Reports Retrival
#  * Copyright (c) 2025 Chapoly1305
#  *
#  * This program is free software: you can redistribute it and/or modify
#  * it under the terms of the GNU General Public License as published by
#  * the Free Software Foundation, version 3.
#  *
#  * This program is distributed in the hope that it will be useful, but
#  * WITHOUT ANY WARRANTY; without even the implied warranty of
#  * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#  * General Public License for more details.
#  *
#  * You should have received a copy of the GNU General Public License
#  * along with this program. If not, see <http://www.gnu.org/licenses/>.
#  */
#
import datetime
import hashlib
import json
import os
import re
import sqlite3
import struct
from typing import Annotated

import simplekml
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, UploadFile, Header, Body

import requests
from fastapi.params import Query, File, Form
from fastapi.responses import JSONResponse, Response
from pytz import timezone

from request_reports import getAuth
from cores.pypush_gsa_icloud import icloud_login_mobileme, generate_anisette_headers
from cryptography.hazmat.primitives.asymmetric import ec

import base64
import logging
import uvicorn
import time
import paho.mqtt.publish as publish
import certifi
import argparse

logging.basicConfig(level=logging.ERROR)

app = FastAPI(
    title="FindMy Gateway API",
    summary="Query Apple's Find My network, allowing none Apple devices to retrieve the location reports.",
    description="### Important Concepts:  "
                "\n**Private Key:** Use for decrypting the report.  "
                "\n**Public Key / Advertisement Key:** Derive from the private key, used for broadcasting.  "
                "\n**Hashed Advertisement Key:** SHA256 hashed public key, used for querying reports.  "
)
app.last_publish_time = 0

CONFIG_PATH = os.path.dirname(os.path.realpath(__file__)) + "/keys/auth.json"

# Parse command line arguments
parser = argparse.ArgumentParser(description='FindMy Gateway API Server')
parser.add_argument('--auth', type=str, choices=['sms', 'trusted_device'], default='sms',
                    help='Authentication method to use: sms or trusted_device (default: sms)')
args = parser.parse_args()

if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        j = json.load(f)
else:
    # Create keys directory if it doesn't exist
    keys_dir = os.path.dirname(CONFIG_PATH)
    os.makedirs(keys_dir, exist_ok=True)
    
    mobileme = icloud_login_mobileme(second_factor=args.auth)
    j = {'dsid': mobileme['dsid'],
         'searchPartyToken': mobileme['delegates']['com.apple.mobileme']['service-data']['tokens'][
             'searchPartyToken']}
    with open(CONFIG_PATH, "w") as f:
        json.dump(j, f)

dsid = j['dsid']
searchPartyToken = j['searchPartyToken']

# Ensure keys directory exists before creating database
keys_dir = os.path.dirname(os.path.realpath(__file__)) + '/keys'
os.makedirs(keys_dir, exist_ok=True)

sq3db = sqlite3.connect(os.path.dirname(os.path.realpath(__file__)) + '/keys/reports.db')
_sq3 = sq3db.cursor()

# SQL query to create a table named 'report' if it does not exist
create_table_query = '''CREATE TABLE IF NOT EXISTS tags (
        hash_adv_key TEXT, private_key TEXT, friendly_name TEXT, mqtt_server TEXT, mqtt_port INTEGER, mqtt_over_tls BOOLEAN,
        mqtt_publish_encryption_key TEXT, mqtt_username TEXT, mqtt_userpass TEXT, mqtt_topic TEXT,
        PRIMARY KEY(private_key,mqtt_server));'''

# Execute the SQL query
_sq3.execute(create_table_query)

# SQL query to create a table named 'report' if it does not exist
create_table_query = '''CREATE TABLE IF NOT EXISTS reports (
id_short TEXT, timestamp INTEGER, datePublished INTEGER, payload TEXT, 
id TEXT, statusCode INTEGER, lat TEXT, lon TEXT, conf INTEGER, PRIMARY KEY(id,payload));'''

# Execute the SQL query
_sq3.execute(create_table_query)


def private_key_from_json(private_keys: str) -> set():
    valid_private_keys = set()
    invalid_private_keys = set()

    re_exp = r"^[-A-Za-z0-9+/]*={0,3}$"
    for key in private_keys.strip().split(','):
        if len(key) != 40 or not re.match(re_exp, key):
            invalid_private_keys.add(key)
        else:
            if len(key) > 0:
                valid_private_keys.add(key)

    return valid_private_keys, invalid_private_keys


def private_to_hashed_key(private_key_b64: str) -> str:
    logging.debug(f"Private Key B64: {private_key_b64}")
    private_key = ec.derive_private_key(int.from_bytes(base64.b64decode(private_key_b64), byteorder="big"),
                                        ec.SECP224R1(), default_backend())

    public_key = private_key.public_key()
    public_key_bytes = public_key.public_numbers().x.to_bytes(28, byteorder='big')

    logging.debug(f"Public Key Bytes: {public_key_bytes.hex()}")
    digest = hashlib.new("sha256")
    digest.update(public_key_bytes)
    sha_value = digest.digest()
    s256_b64 = base64.b64encode(sha_value).decode("ascii")
    logging.debug(f"Hash ADV Key: {s256_b64}")
    return s256_b64


def sha256(data):
    digest = hashlib.new("sha256")
    digest.update(data)
    return digest.digest()


def decrypt(enc_data, algorithm_dkey, mode):
    decryptor = Cipher(algorithm_dkey, mode, default_backend()).decryptor()
    return decryptor.update(enc_data) + decryptor.finalize()


def decrypt_payload(report: str, private_key: str) -> {}:
    data = base64.b64decode(report)
    priv = int.from_bytes(base64.b64decode(private_key), byteorder="big")

    timestamp = int.from_bytes(data[0:4], byteorder="big") + 978307200
    if len(data) == 88:
        confidence = int.from_bytes(data[4:5], byteorder="big")
        eph_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP224R1(), data[5:62])
        shared_key = ec.derive_private_key(priv, ec.SECP224R1(), default_backend()).exchange(ec.ECDH(), eph_key)
        symmetric_key = sha256(shared_key + b'\x00\x00\x00\x01' + data[5:62])
        ciper_txt = data[62:72]
        auth_tag = data[72:]
    elif len(data) == 89:
        confidence = int.from_bytes(data[4:6], byteorder="big")
        eph_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP224R1(), data[6:63])
        shared_key = ec.derive_private_key(priv, ec.SECP224R1(), default_backend()).exchange(ec.ECDH(), eph_key)
        symmetric_key = sha256(shared_key + b'\x00\x00\x00\x01' + data[6:63])
        ciper_txt = data[63:73]
        auth_tag = data[73:]
    else:
        return {'decrypt_success': False, 'fail_reason': 'Invalid Payload Length'}

    iv = symmetric_key[16:]
    decryption_key = symmetric_key[:16]
    clear_text = decrypt(ciper_txt, algorithms.AES(decryption_key), modes.GCM(iv, auth_tag))

    result = {}
    latitude = struct.unpack(">i", clear_text[0:4])[0] / 10000000.0
    longitude = struct.unpack(">i", clear_text[4:8])[0] / 10000000.0
    horizontal_accuracy = int.from_bytes(clear_text[8:9], byteorder="big")
    status = int.from_bytes(clear_text[9:10], byteorder="big")

    result['timestamp'] = timestamp
    result['isodatetime'] = datetime.datetime.fromtimestamp(timestamp).isoformat()
    result['lat'] = latitude
    result['lon'] = longitude
    result['confidence'] = confidence
    result['status'] = status
    result['horizontal_accuracy'] = horizontal_accuracy
    result['decrypt_success'] = True
    result['fail_reason'] = ''
    return result


def input_sanitize(input_str: str) -> str:
    input_str = input_str.strip().strip().replace(" ", "")
    if len(input_str) in [44, 40]:
        if re.match(r"^[-A-Za-z0-9+/]*={0,3}$", input_str):
            return input_str
    if len(input_str) in [64, 56]:
        if re.match(r"^[A-Fa-f0-9]*$", input_str):
            return input_str
    logging.debug(f"Invalid Input: {input_str}")
    return ""


def get_report_from_upstream(advertisement_keys: str, hours: int) -> {}:
    re_exp = r"^[-A-Za-z0-9+/]*={0,3}$"
    advertisement_keys_list = []
    advertisement_keys_invalid_list = set()

    for key in advertisement_keys.strip().replace(" ", "").split(','):
        if len(key) != 44 or not re.match(re_exp, key):
            if key != "":
                advertisement_keys_invalid_list.add(key)
        else:
            if len(key) > 0:
                advertisement_keys_list.append(key)

    if len(advertisement_keys_invalid_list) > 0:
        return JSONResponse(
            content={"error": f"Invalid Hashed Advertisement Base64 Key(s): {advertisement_keys_invalid_list}"},
            status_code=400)
    if len(advertisement_keys_list) == 0:
        return JSONResponse(
            content={"error": f"No valid Hashed Advertisement Base64 Key(s) found"},
            status_code=400)

    unix_epoch = int(datetime.datetime.now().timestamp())
    start_date = unix_epoch - (60 * 60 * hours)
    data = {"search": [{"startDate": start_date * 1000, "endDate": unix_epoch * 1000, "ids": advertisement_keys_list}]}

    r = requests.post("https://gateway.icloud.com/acsnservice/fetch",
                      auth=(dsid, searchPartyToken),
                      headers=generate_anisette_headers(),
                      json=data)

    return json.loads(r.content.decode(encoding='utf-8'))


@app.post("/SingleDeviceEncryptedReports/", summary="Retrieve reports for one device at a time.")
async def single_device_encrypted_reports(
        advertisement_key: str = Query(
            description="Advertisement Key. Hashed public key in Base64 or HexString format",
            regex=r"^[-A-Za-z0-9+/]*={0,3}$"),
        hours: int = Query(1, description="Hours to search back in time", ge=1, le=24), ):
    """
    Enter one hashed advertisement key in hex string or base64 format, and the hours to search back in time. <br>
    The API will attempt to retrieve the reports from Apple and provide as a JSON response. <br>
    """
    advertisement_key_san = input_sanitize(advertisement_key)
    if advertisement_key_san == "":
        return JSONResponse(
            content={"error": f"Invalid Key: {advertisement_key}"},
            status_code=400)

    if len(advertisement_key_san) == 64:
        advertisement_key_san = base64.b64encode(bytes.fromhex(advertisement_key_san)).decode("ascii")
    unix_epoch = int(datetime.datetime.now().timestamp())
    start_date = unix_epoch - (60 * 60 * hours)

    data = {"search": [{"startDate": start_date * 1000, "endDate": unix_epoch * 1000,
                        "ids": [advertisement_key_san]}]}

    r = requests.post("https://gateway.icloud.com/acsnservice/fetch",
                      auth=(dsid, searchPartyToken),
                      headers=generate_anisette_headers(),
                      json=data)

    return json.loads(r.content.decode(encoding='utf-8'))


@app.post("/MultipleDeviceEncryptedReports/", summary="Retrieve reports for multiple devices at a time.")
async def multiple_device_encrypted_reports(
        advertisement_keys: Annotated[str, Body(
            description="Hashed Advertisement Base64 Key. Separate each key by a comma.",
            media_type="text/plain")],

        hours: int = Body(1, description="Hours to search back in time", ge=1, le=24)):
    """
    Enter one or multiple hashed advertisement key(s) in base64 or HexString format,
    and the hours to search back in time. <br>
    The API will attempt to retrieve the reports from Apple and provide as a JSON response. <br>
    """
    key_len = len(advertisement_keys.split(',')[0].strip().replace(" ", ""))
    if key_len != 44:
        if key_len == 64:
            # encode each key to base64, form new string
            advertisement_keys = ",".join([base64.b64encode(bytes.fromhex(key)).decode("ascii") for key in
                                           advertisement_keys.split(',')])
        else:
            return JSONResponse(
                content={"error": f"Invalid Hashed Advertisement Key(s): {advertisement_keys}"},
                status_code=400)
    return get_report_from_upstream(advertisement_keys, hours)


@app.post("/SingleDecrypt/", summary="Decrypt reports for one or many devices.")
async def report_decrypt_single(
        private_keys: Annotated[str | None, Header(
            description="**Private Key is a secret and shall not be provided to any untrusted website!**")] = None,
        reports: UploadFile = File(..., max_size=5 * 1024 * 1024,
                                   description="The JSON response from MultipleDeviceEncryptedReports or "
                                               "SingleDeviceEncryptedReports"),
        skip_invalid: bool = Query(description="Ignore report and private mismatch", default=False)):
    """
    Upload the JSON response from MultipleDeviceEncryptedReports or SingleDeviceEncryptedReports,<br>
    and the private key(s) in base64 format to decrypt the reports.<br>
    Choose True or False to skip any format invalid private key <br>
    """
    valid_private_keys = set()
    invalid_private_keys = set()

    key_dict = {}
    for key in private_keys.strip().split(','):

        key_san = input_sanitize(key)
        if key_san == "":
            invalid_private_keys.add(key)
        else:
            if len(key_san) == 40:
                valid_private_keys.add(key_san)
            elif len(key_san) == 56:
                valid_private_keys.add(base64.b64encode(bytes.fromhex(key_san)).decode("ascii"))
            else:
                invalid_private_keys.add(key)

    for key in valid_private_keys:
        try:
            key_dict[private_to_hashed_key(key)] = key
        except Exception as e:
            logging.error(f"Private Key Decode Failed: {e}", exc_info=True)
            invalid_private_keys.add(key)

    valid_reports = {}
    invalid_reports = set()

    try:
        loaded_reports = json.loads(reports.file.read())
        logging.debug("JSON Loaded")
        if loaded_reports['statusCode'] == '200':
            logging.debug("Status Code 200")
        else:
            return JSONResponse(
                content={"error": f"Upstream informed an error. {loaded_reports['statusCode']}"},
                status_code=400)

        reports = loaded_reports['results']
        for report in reports:
            logging.debug(f"Processing {report}")
            if report['id'] in valid_reports:
                valid_reports[report['id']].append(report)
            else:
                logging.debug(f"ID is not in dict, creating list and adding ...")
                valid_reports[report['id']] = []
                valid_reports[report['id']].append(report)

    except Exception as e:
        logging.error(f"JSON Decode Failed: {e}", exc_info=True)
        return JSONResponse(
            content={"error": f"Invalid JSON Format, Report Decode Failed"},
            status_code=400)

    if len(valid_reports) == 0:
        return JSONResponse(
            content={"error": f"No valid reports found"},
            status_code=400)

    for hash_key in valid_reports:
        if hash_key in key_dict:
            for report in valid_reports.get(hash_key):
                clear_text = decrypt_payload(report['payload'], key_dict[hash_key])
                report['decrypted_payload'] = clear_text
        else:
            invalid_reports.add(hash_key)

    if len(invalid_reports) > 0 and not skip_invalid:
        return JSONResponse(
            content={"error": f"Invalid Key(s): {invalid_reports}"},
            status_code=400)

    return valid_reports


@app.post("/MultipleDecrypt/", summary="Decrypt reports for one or many devices.")
async def report_decrypt_multiple(
        private_keys: UploadFile = File(..., description="File containing private keys, one per line"),
        reports: UploadFile = File(...,
                                   description="The JSON response from MultipleDeviceEncryptedReports or SingleDeviceEncryptedReports"),
        skip_invalid: bool = Form(False, description="Ignore report and private key mismatch")
):
    """
    Upload the JSON response from MultipleDeviceEncryptedReports or SingleDeviceEncryptedReports,<br>
    and the private key(s) in base64 format to decrypt the reports.<br>
    Choose True or False to skip any format invalid private key <br>
    """
    valid_private_keys = set()
    invalid_private_keys = set()

    key_dict = {}
    # Read private keys from file
    private_keys_content = await private_keys.read()
    private_keys_list = private_keys_content.decode().strip().split('\n')
    for key in private_keys_list:
        key_san = input_sanitize(key)
        if key_san == "":
            invalid_private_keys.add(key)
        else:
            if len(key_san) == 40:
                valid_private_keys.add(key_san)
            elif len(key_san) == 56:
                valid_private_keys.add(base64.b64encode(bytes.fromhex(key_san)).decode("ascii"))
            else:
                invalid_private_keys.add(key)
                logging.debug(f"Invalid Key kml, length {len(key_san)}")

    valid_reports = {}
    invalid_reports = set()

    try:
        loaded_reports = json.loads(reports.file.read())
        logging.debug("JSON Loaded")
        if loaded_reports['statusCode'] == '200':
            logging.debug("Status Code 200")
        else:
            return JSONResponse(
                content={"error": f"Upstream informed an error. {loaded_reports['statusCode']}"},
                status_code=400)

        reports = loaded_reports['results']
        for report in reports:
            logging.debug(f"Processing {report}")
            if report['id'] in valid_reports:
                valid_reports[report['id']].append(report)
            else:
                logging.debug(f"ID is not in dict, creating list and adding ...")
                valid_reports[report['id']] = []
                valid_reports[report['id']].append(report)

    except Exception as e:
        logging.error(f"JSON Decode Failed: {e}", exc_info=True)
        return JSONResponse(
            content={"error": f"Invalid JSON Format, Report Decode Failed"},
            status_code=400)

    if len(valid_reports) == 0:
        return JSONResponse(
            content={"error": f"No valid reports found"},
            status_code=400)
    for key in valid_private_keys:
        try:
            key_dict[private_to_hashed_key(key)] = key
        except Exception as e:
            logging.error(f"Private Key Decode Failed: {e}", exc_info=True)
            invalid_private_keys.add(key)
    for hash_key in valid_reports:
        if hash_key in key_dict:
            for report in valid_reports.get(hash_key):
                clear_text = decrypt_payload(report['payload'], key_dict[hash_key])
                report['decrypted_payload'] = clear_text
        else:
            invalid_reports.add(hash_key)

    if len(invalid_reports) > 0 and not skip_invalid:
        return JSONResponse(
            content={"error": f"Invalid Key(s): {invalid_reports}"},
            status_code=400)

    if len(valid_reports) == 0:
        return JSONResponse(
            content={"error": f"No valid reports found"},
            status_code=400)

    return valid_reports


@app.post("/MultiDecryptToKML/", summary="Decrypt reports for one or many devices.")
async def report_decrypt_kml(
        private_keys: UploadFile = File(..., description="File containing private keys, one per line"),
        reports: UploadFile = File(...,
                                   description="The JSON response from MultipleDeviceEncryptedReports or SingleDeviceEncryptedReports"),
        skip_invalid: bool = Form(False, description="Ignore report and private key mismatch")
):
    """
    Upload the JSON response from MultipleDeviceEncryptedReports or SingleDeviceEncryptedReports,<br>
    and the private key(s) in base64 format to decrypt the reports.<br>
    Choose True or False to skip any format invalid private key <br>
    """
    valid_private_keys = set()
    invalid_private_keys = set()

    key_dict = {}
    # Read private keys from file
    private_keys_content = await private_keys.read()
    private_keys_list = private_keys_content.decode().strip().split('\n')
    for key in private_keys_list:
        key_san = input_sanitize(key)
        if key_san == "":
            invalid_private_keys.add(key)
        else:
            if len(key_san) == 40:
                valid_private_keys.add(key_san)
            elif len(key_san) == 56:
                valid_private_keys.add(base64.b64encode(bytes.fromhex(key_san)).decode("ascii"))
            else:
                invalid_private_keys.add(key)
                logging.debug(f"Invalid Key kml, length {len(key_san)}")

    valid_reports = {}
    invalid_reports = set()

    try:
        loaded_reports = json.loads(reports.file.read())
        logging.debug("JSON Loaded")
        if loaded_reports['statusCode'] == '200':
            logging.debug("Status Code 200")
        else:
            return JSONResponse(
                content={"error": f"Upstream informed an error. {loaded_reports['statusCode']}"},
                status_code=400)

        reports = loaded_reports['results']
        for report in reports:
            logging.debug(f"Processing {report}")
            if report['id'] in valid_reports:
                valid_reports[report['id']].append(report)
            else:
                logging.debug(f"ID is not in dict, creating list and adding ...")
                valid_reports[report['id']] = []
                valid_reports[report['id']].append(report)

    except Exception as e:
        logging.error(f"JSON Decode Failed: {e}", exc_info=True)
        return JSONResponse(
            content={"error": f"Invalid JSON Format, Report Decode Failed"},
            status_code=400)

    if len(valid_reports) == 0:
        return JSONResponse(
            content={"error": f"No valid reports found"},
            status_code=400)
    for key in valid_private_keys:
        try:
            key_dict[private_to_hashed_key(key)] = key
        except Exception as e:
            logging.error(f"Private Key Decode Failed: {e}", exc_info=True)
            invalid_private_keys.add(key)
    for hash_key in valid_reports:
        if hash_key in key_dict:
            for report in valid_reports.get(hash_key):
                clear_text = decrypt_payload(report['payload'], key_dict[hash_key])
                report['decrypted_payload'] = clear_text
        else:
            invalid_reports.add(hash_key)

    if len(invalid_reports) > 0 and not skip_invalid:
        return JSONResponse(
            content={"error": f"Invalid Key(s): {invalid_reports}"},
            status_code=400)

    if len(valid_reports) == 0:
        return JSONResponse(
            content={"error": f"No valid reports found"},
            status_code=400)

    # Create a new KML object
    kml = simplekml.Kml()
    ny_tz = timezone('America/New_York')

    # Locate a collection of reports by using Base64 of Hashed Public Key
    for hash_key in valid_reports:
        for report in valid_reports.get(hash_key):
            payload = report['decrypted_payload']
            timestamp = payload['timestamp']
            confidence = payload['confidence']

            # Check if timestamp is in milliseconds
            if timestamp > 1e12:  # If timestamp is in milliseconds
                timestamp = timestamp / 1000  # Convert to seconds

            utc_time = datetime.datetime.utcfromtimestamp(timestamp)
            utc_time = utc_time.replace(tzinfo=timezone('UTC'))
            lat = payload['lat']
            lon = payload['lon']

            ny_time = utc_time.astimezone(ny_tz)
            time_str = ny_time.strftime('%Y-%m-%d %H:%M:%S %Z')

            # Create a placemark for each point
            pnt = kml.newpoint(name=time_str, coords=[(lon, lat)])
            pnt.timestamp.when = ny_time.isoformat()  # Set the timestamp for the placemark

    kml_string = kml.kml()
    return Response(
        content=kml_string,
        media_type="application/vnd.google-earth.kml+kml",
        headers={
            "Content-Disposition": "attachment; filename=report.kml"
        }
    )


@app.post("/KeyToMonitor/", summary="Add a key to monitor db.")
async def key_to_monitor(
        private_key: Annotated[str | None, Body(
            description="**Private Key is a secret and shall not be provided to any untrusted website!**")] = None,
        friendly_name: Annotated[str, Body(description="Friendly name for the key")] = "HayTag",
        mqtt_server: Annotated[str, Body(description="MQTT Server")] = "127.0.0.1",
        mqtt_port: Annotated[int, Body(description="MQTT Port")] = 1883,
        # mqtt_topic: Annotated[str, Body(description="MQTT Topic")] = "",
        # mqtt_publish_encryption_key: Annotated[str, Body(description="MQTT Publish Encryption Key")] = "",
        mqtt_username: Annotated[str, Body(description="MQTT Username")] = "USERNAME",
        mqtt_userpass: Annotated[str, Body(description="MQTT Userpass")] = "PASSWORD",
        mqtt_over_tls: Annotated[bool, Body(description="MQTT over TLS")] = False,
):
    """
    **Private Key and UserPass are secrets, you shall not provide them to any untrusted website!**<br>
    **Private Key and UserPass are secrets, you shall not provide them to any untrusted website!**<br>
    **Private Key and UserPass are secrets, you shall not provide them to any untrusted website!**<br>

    When this api is triggered, it will save the private key and MQTT credentials to the database.

    Example,\n
    ```JSON
    {
      "private_key": "TAG PRIVATE KEY",
      "friendly_name": "OwnTags",
      "mqtt_server": "xxx.com or 222.111.0.123",
      "mqtt_port": 8883,
      "mqtt_topic": "Does Not Work at this moment. ",
      "mqtt_publish_encryption_key": "Does Not Work at this moment. ",
      "mqtt_username": "USERNAME",
      "mqtt_userpass": "PASSWORD",
      "mqtt_over_tls": true or false
    }
    ```
    """

    mqtt_topic, mqtt_publish_encryption_key = "", ""
    valid_private_keys, invalid_private_keys = private_key_from_json(private_key)

    if len(valid_private_keys) == 0:
        return JSONResponse(
            content={"error": f"No valid Private Key(s) found"},
            status_code=400)

    logging.debug(f"private_key: {private_key}, friendly_name: {friendly_name}, mqtt_server: {mqtt_server}, \n"
                  f"mqtt_port: {mqtt_port}, mqtt_publish_encryption_key length: {len(mqtt_publish_encryption_key)}, \n"
                  f"mqtt_username: {mqtt_username}, mqtt_userpass length: {len(mqtt_userpass)}, mqtt_over_tls: {mqtt_over_tls}")

    for key in valid_private_keys:
        query = "INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        parameters = (private_to_hashed_key(key), key, friendly_name, mqtt_server, mqtt_port, mqtt_over_tls,
                      mqtt_publish_encryption_key, mqtt_username, mqtt_userpass, mqtt_topic)
        _sq3.execute(query, parameters)

    sq3db.commit()
    return JSONResponse(
        content={"success": f"Private key added to monitor db"},
        status_code=200)


# Get the reports from the upstream and decrypt them, save the result to the reports table
def sync_latest_decrypted_reports():
    hash_adv_keys = _sq3.execute("SELECT hash_adv_key FROM tags")
    hash_adv_keys = set([item[0] for item in hash_adv_keys])

    logging.debug(f"hash_adv_keys: {hash_adv_keys}")
    if len(hash_adv_keys) == 0:
        logging.error(f"No Report available, or Upstream informed an error.", exc_info=True)
        return

    reports = get_report_from_upstream(",".join(hash_adv_keys), 1)

    if "results" in reports:
        for report in reports["results"]:
            if report["id"] in hash_adv_keys:
                clear_text = decrypt_payload(report['payload'], _sq3.execute(
                    "SELECT private_key FROM tags WHERE hash_adv_key = ?", (report["id"],)).fetchone()[0])

                # id_short TEXT, timestamp INTEGER, datePublished INTEGER, payload TEXT,
                # id TEXT, statusCode INTEGER, lat TEXT, lon TEXT, conf INTEGER

                logging.debug(report)
                logging.debug(clear_text)
                query = "INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                parameters = (report["id"][:7], clear_text['timestamp'], report['datePublished'], report['payload'],
                              report['id'], clear_text['status'], clear_text['lat'], clear_text['lon'],
                              clear_text['confidence'])
                _sq3.execute(query, parameters)
        sq3db.commit()
    else:
        logging.error(f"Upstream informed an error. {reports['statusCode']}", exc_info=True)


@app.post("/Publish_MQTT/", summary="Trigger a publish action to MQTT Servers")
async def publish_mqtt():
    """
    When this api is triggered, it will read all the private keys have been register by using the api "KeyToMonitor",
    query the latest reports from Apple, save the reports to database,
    then and publish it to the MQTT server which previously declared and saved in the database.
    """

    if time.time() - app.last_publish_time < 60:
        return JSONResponse(
            content={
                "error": f"Publish MQTT too frequently, please wait for "
                         f"{int(60 - (time.time() - app.last_publish_time))} seconds"},
            status_code=400)
    else:
        app.last_publish_time = time.time()

    ca_path = certifi.where()
    # hash_adv_key TEXT, private_key TEXT, friendly_name TEXT, mqtt_server TEXT, mqtt_port INTEGER, mqtt_over_tls BOOLEAN,
    # mqtt_publish_encryption_key TEXT, mqtt_username TEXT, mqtt_userpass TEXT, mqtt_topic TEXT

    sync_latest_decrypted_reports()

    sql_query = """
    WITH RankedReports AS (
      SELECT
        hash_adv_key,
        friendly_name,
        mqtt_server,
        mqtt_port,
        lat,
        lon,
        timestamp,
        mqtt_over_tls,
        mqtt_publish_encryption_key,
        mqtt_username,
        mqtt_userpass,
        mqtt_topic,
        conf,
        ROW_NUMBER() OVER(PARTITION BY hash_adv_key ORDER BY timestamp DESC) AS rn
      FROM tags
      JOIN reports ON reports.id = tags.hash_adv_key
      WHERE lat IS NOT NULL AND lon IS NOT NULL
    )
    SELECT
      hash_adv_key,
      friendly_name,
      mqtt_server,
      mqtt_port,
      lat,
      lon,
      timestamp,
      mqtt_over_tls,
      mqtt_publish_encryption_key,
      mqtt_username,
      mqtt_userpass,
      mqtt_topic,
      conf
    FROM RankedReports
    WHERE rn = 1;
    """
    tags = _sq3.execute(sql_query).fetchall()

    logging.debug(f"tags to send. {tags}")

    if len(tags) == 0:
        return JSONResponse(
            content={"error": f"No valid report found"},
            status_code=400)

    for tag in tags:
        try:
            logging.debug(f"\n"
                          f"tag[0]: {tag[0]} \n"
                          f"tag[1]: {tag[1]} \n"
                          f"tag[2]: {tag[2]} \n"
                          f"tag[3]: {tag[3]} \n"
                          f"tag[4]: {tag[4]} \n"
                          f"tag[5]: {tag[5]} \n"
                          f"tag[6]: {tag[6]} \n"
                          f"tag[7]: {tag[7]} \n"
                          f"tag[8]: {tag[8]} \n"
                          f"tag[9]: {tag[9]} \n"
                          f"tag[10]: {tag[10]} \n"
                          f"tag[11]: {tag[11]}")

            # https://owntracks.org/booklet/tech/json/#_typelocation
            report = {"_type": "location",
                      "lat": float(tag[4]),
                      "lon": float(tag[5]),
                      "tst": float(tag[6]),
                      "tid": tag[1]
                      }
            escape_keyname = tag[0].replace("/", "_")

            if tag[7]:
                logging.info(f"Publishing MQTT for {tag[0]} to {tag[2]}")
                publish.single(
                    topic=f"owntracks/{tag[9]}/{tag[1]}_{escape_keyname[:4]}",
                    payload=json.dumps(report, separators=(',', ':')),
                    qos=1, retain=True, hostname=tag[2], client_id=tag[9],
                    port=int(tag[3]), keepalive=60, will=None, tls={"ca_certs": ca_path},
                    auth={'username': tag[9], 'password': tag[10]},
                    transport="tcp")

            else:
                logging.info(f"Publishing MQTT for {tag[0]} to {tag[2]}")
                publish.single(
                    topic=f"owntracks/{tag[9]}/{tag[1]}_{escape_keyname[:4]}",
                    payload=json.dumps(report, separators=(',', ':')),
                    qos=1, retain=True, hostname=tag[2], client_id=tag[9],
                    port=int(tag[3]), keepalive=60, will=None, tls=None,
                    auth={'username': tag[9], 'password': tag[10]},
                    transport="tcp")
        except Exception as e:
            logging.error(f"Publish MQTT Failed: {e}", exc_info=True)
            pass
    return JSONResponse(
        content={"success": f"Published MQTT"},
        status_code=200)


@app.post("/Tag_Removal/", summary="Remove everything from Database with given hashed, advertisement, or private key.")
async def tag_removal(
        keys: Annotated[str, Query(
            description="Key in Base64 format. Separate each key by a comma.")]):
    re_exp = r"^[-A-Za-z0-9+/]*={0,3}$"

    keys_set = set()
    for key in keys.strip().replace(" ", "").split(','):
        if len(key) > 0 and re.match(re_exp, key):
            keys_set.add(key)

    if len(keys_set) == 0:
        return JSONResponse(
            content={"error": f"No valid Base64 Key(s) found"},
            status_code=400)

    for key in keys_set:
        _sq3.execute("DELETE FROM tags WHERE hash_adv_key = ? OR private_key = ?", (key, key))
        _sq3.execute("DELETE FROM reports WHERE id = ?", (key,))

    sq3db.commit()
    return JSONResponse(
        content={"success": f"Key(s) removed from database"},
        status_code=200)


if __name__ == "__main__":
    getAuth()
    uvicorn.run("web_service:app", host="127.0.0.1", port=8000, log_level="error")
