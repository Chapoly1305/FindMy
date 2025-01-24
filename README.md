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

You will likely receive a response of, 

```json
{"X-Apple-I-Client-Time":"2025-01-24T15:28:51Z","X-Apple-I-MD":"AAAABQAAABDKVqqoAAAAijx167JpHNPfAAAABA==","X-Apple-I-MD-LU":"3AAAA12E405E273D93721E8B171AAAA2B11138C59ABCDCCCC59E9133DD84FABC","X-Apple-I-MD-M":"P5bJSBx8nqXL0vmoMMTCrSxAAAAAAAAAAA3VXQXnL2Vm/lpm/40HqLNIJ/zmvo0WnjxDayJYlTX","X-Apple-I-MD-RINFO":"17106176","X-Apple-I-SRL-NO":"0","X-Apple-I-TimeZone":"UTC","X-Apple-Locale":"en_US","X-MMe-Client-Info":"<MacBookPro13,2> <macOS;13.1;22C65> <com.apple.AuthKit/1 (com.apple.dt.Xcode/3594.4.19)>","X-Mme-Device-Id":"FE1ED333-1111-4321-1234-68AEC074E926"}
```

4. Then, clone this repository, Navigate to `FindMy` directory, and install the required python packages:

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



Hint: This web service will die if the shell exited or system reboot. You could use `nohup`, `screen`, or set up a systemd service to keep it alive.



## API Usage

The APIs are created with FastAPI, the documentations are written inline and can be accessed on website path http://127.0.0.1:8000/docs or http://127.0.0.1:8000/redoc. 


## Traditional Key File Method

### generate_keys.py

Use the `generate_keys.py` script to generate the required keys. The script will generate a `.keys`
or multiple files for each device you want to use. Each `.keys` file will contain the private key, the public key
(also called advertisement key) and the hashed advertisement key. As the name suggests, the private key is a secret
and should not be shared. The public key (advertisement key) is used for broadcasting the BLE message, this is also
being asked by the `hci.py` script in openhaystack project. The hashed advertisement key is for requesting location
reports from Apple.

### request_reports.py

Use the `request_reports.py` script to request location reports from Apple. The script will read the `.keys` files and
request location reports for each device. The script will also attempt to log in and provided Apple account and save
the session cookies in `auth.json` file. The reports are stored in the `reports` database.



The anisetter docker service shall run on the same device of this project. If the anisetter has started, then run:

```bash
./request_reports.py # Without any arguments, it will read all the .keys files under current directory.
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
