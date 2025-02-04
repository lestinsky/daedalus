#!/usr/bin/env python
"""
Daedalus data aggregator and grafana interface

Jan 2025 xaratustrah@github

"""

import zmq
import json
import toml
import os
import sys
import argparse
import random
import time
import threading
import requests
from loguru import logger
from influxdb_client import InfluxDBClient

# REST shared variables
shared_json1 = {}
shared_json2 = {}

# Validate the TOML file
def validate_config(config):
    required_keys = [
        "mcu.address",
        "mcu.port",
        "tcu.address",
        "tcu.port",
        "grafana.address",
        "grafana.port",
        "grafana.org",
        "grafana.bucket",
        "grafana.token",
        "restapi.resturl1",
        "restapi.resturl2",
    ]
    for key in required_keys:
        keys = key.split(".")
        conf = config
        for k in keys:
            if k not in conf:
                raise ValueError(f"Missing required key: {key}")
            conf = conf[k]

def flatten_dict(d, parent_key="", sep="_"):
    items = []
    for k, v in d.items():
        if isinstance(v, dict):
            items.extend(flatten_dict(v, "", sep=sep).items())
        else:
            items.append((k, v))
    return dict(items)

def calculate_jet_velocity(temperature, nozzle_pressure):
    # meter per seconds
    # here comes the real forumla, for now just a random number
    return random.uniform(300, 1500)


def calculate_target_density(velocity, s1, s2, s3, s4):
    # particles per square centimeter
    # here comes the real forumla, for now just a random number
    return random.uniform(1.0e10, 1.0e13)

def validate_arguments(args):
    if args.log and not args.logfile:
        raise ValueError('Filename must be provided when logging is enabled')

# Function to update the first shared variable
def update_variable1(url):
    global shared_json1
    s = requests.Session()
    r = s.get(url, stream=True)
    for line in r.iter_lines():
        if line:
            byte_array_str = line.decode("utf-8")
            json_str = byte_array_str.replace("data: ", "")
            shared_json1 = json.loads(json_str)

# Function to update the second shared variable
def update_variable2(url):
    global shared_json2
    s = requests.Session()
    r = s.get(url, stream=True)
    for line in r.iter_lines():
        if line:
            byte_array_str = line.decode("utf-8")
            json_str = byte_array_str.replace("data: ", "")
            shared_json2 = json.loads(json_str)
       
def process_jsons(json1, json2):
    name1 = ""
    value1 = 0    
    epoch_time1 = 0
    
    name2 = ""
    value2 = 0    
    epoch_time2 = 0

    try:
        name1 = json1['sourceInfo']['deviceName']
        value1 = json1['data']['pressure'] / 100, # convert Pa to mbar
        epoch_time1 = json1['data']['timestampAcq'] / 1_000_000_000
        
        name2 = json2['sourceInfo']['deviceName']
        value2 = json2['data']['pressure'] / 100, # convert Pa to mbar
        epoch_time2 = json2['data']['timestampAcq'] / 1_000_000_000
                
    except(KeyError):
        pass # do nothing for now.

    s4 = {
        "name": "vacuum",
        "ch": 7,
        "dev": name1,
        "ldev": name1,
        "value": value1,
        "epoch_time": epoch_time1
    }
    e4 = {
        "name": "vacuum",
        "ch": 8,
        "dev": name2,
        "ldev": name2,
        "value": value2,
        "epoch_time": epoch_time2
    }

    print("\n\n", value1.__class__)

    return {
        "s4": s4,
        "e4": e4,
    }
         
def main():
    # Parse command line arguments
    
    logger.remove(0)
    logger.add(sys.stdout, level="INFO")

    parser = argparse.ArgumentParser(
        description="Subscriber script with TOML configuration."
    )
    parser.add_argument(
        "--cfg", type=str, required=True, help="Path to the configuration TOML file."
    )
    
    parser.add_argument('--debug', action='store_true', help='Enable debugging mode')
    parser.add_argument('--log', action='store_true', help='Enable logging mode')
    parser.add_argument('--logfile', type=str, help='Log file name')

    args = parser.parse_args()

    validate_arguments(args)

    if args.debug:
        logger.info('Debugging mode is enabled')
    if args.log:
        logger.info(f'Logging to file: {args.logfile}')


    # Read and validate the configuration from the TOML file
    config_path = args.cfg
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"TOML file not found: {config_path}")

    config = toml.load(config_path)
    validate_config(config)

    # Extract socket information from the configuration
    address1 = config["mcu"]["address"]
    port1 = config["mcu"]["port"]
    address2 = config["tcu"]["address"]
    port2 = config["tcu"]["port"]
    
    influx_url=f'{config["grafana"]["address"]}:{config["grafana"]["port"]}'
    influx_token = config["grafana"]["token"]
    influx_org = config["grafana"]["org"]
    influx_bucket = config["grafana"]["bucket"]

    resturl1 = config["restapi"]["resturl1"]
    resturl2 = config["restapi"]["resturl2"]
    
    # ZMQ setup
    context = zmq.Context()

    socket_mcu = context.socket(zmq.SUB)
    socket_mcu.connect(f"{address1}:{port1}")
    socket_mcu.setsockopt_string(zmq.SUBSCRIBE, "")

    socket_tcu = context.socket(zmq.SUB)
    socket_tcu.connect(f"{address2}:{port2}")
    socket_tcu.setsockopt_string(zmq.SUBSCRIBE, "")

    # REST API
    # Create and start the first thread
    update_thread1 = threading.Thread(target=update_variable1, kwargs={'url' : resturl1})
    update_thread1.daemon = True  # Daemon thread will exit when the main program exits
    update_thread1.start()

    # Create and start the second thread
    update_thread2 = threading.Thread(target=update_variable2, kwargs={'url' : resturl2})
    update_thread2.daemon = True  # Daemon thread will exit when the main program exits
    update_thread2.start()

    while True:
        try:
            message_mcu = socket_mcu.recv_string()
            data_mcu = json.loads(message_mcu)

            message_tcu = socket_tcu.recv_string()
            data_tcu = json.loads(message_tcu)

            json_from_rest = process_jsons(shared_json1, shared_json2)
            # print(json_from_rest)
            combined_json = data_tcu | data_mcu | json_from_rest
            #print(combined_json)

            s1 = combined_json.get("s1")["value"]
            s2 = combined_json.get("s2")["value"]
            s3 = combined_json.get("s3")["value"]
            s4 = combined_json.get("s4")["value"]
            
            nozzle_pressure = combined_json.get("nozzle_pressure")["value"]
            
            # take temperature Cold head T1 for calculations
            temperature = combined_json.get("temperature1")["value"]

            velocity = calculate_jet_velocity(temperature, nozzle_pressure)
            density = calculate_target_density(velocity, s1, s2, s3, s4)

            calculated_json = {
                "velocity": {
                    "name": "velocity",
                    "dev":"GJ",
                    "value": velocity,
                    "epoch_time": time.time(),
                },
                "density": {
                    "name": "density",
                    "dev":"GJ",
                    "value": density,
                    "epoch_time": time.time()
                },
            }

            final_json = combined_json | calculated_json

            string_list = []
            
            for key, value in final_json.items():
                flat_dict = flatten_dict(value)
                flat_string = ",".join([f"{k}={v}" for k, v in flat_dict.items()])
                
                flat_string = flat_string.replace("name=", "").replace(",value", " value").replace(",epoch_time=", " ")
                flat_string = flat_string[:flat_string.rfind(".")]
            #    logger.info(flat_string)
                string_list.append(flat_string)

            single_string = "\n".join(string_list)                
            with InfluxDBClient(url=influx_url, token=influx_token, debug=args.debug) as client:
                with client.write_api() as writer:
                    writer.write(bucket=influx_bucket, org=influx_org, record=single_string, write_precision="s")
                            
            if args.log:
                with open(f'{args.logfile}', 'a') as f:
                    f.write(flat_string + "\n")
                        
        except (EOFError, KeyboardInterrupt):
            logger.success("\nUser input cancelled. Aborting...")
            break


# -------

if __name__ == "__main__":
    main()
