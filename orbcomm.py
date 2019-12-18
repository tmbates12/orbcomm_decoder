import threading
import socket
import collections
import numpy as np
import time
import math
import datetime as dt
import more_itertools as mi
import binascii as ba
import pyproj

pending_bits = collections.deque()
pending_frames = collections.deque()
pending_packets = collections.deque()


def fletcher_decode(data):
    sum1 = 0
    sum2 = 0
    for x in data:
        sum1 = (sum1 + x) & 0xFF
        sum2 = (sum2 + sum1) & 0xFF
    return sum1 + sum2


def gps2date(week, seconds):
    epoch = dt.datetime(1980, 1, 6)
    return epoch + dt.timedelta(weeks=week) + dt.timedelta(seconds=seconds)


def ecef2lla(x, y, z):
    p1 = pyproj.Proj(proj='geocent', ellps='WGS84', datum='WGS84')
    p2 = pyproj.Proj(proj='latlong', ellps='WGS84', datum='WGS84')
    lon, lat, alt = pyproj.transform(p1, p2, x, y, z, radians=False)
    return lat, lon, alt


def synch_handler(packet):
    if fletcher_decode(packet) != 0:
            return
    scid = "FM-{}".format(packet[3])
    frame_cnt = (packet[6] & 0xF0) >> 4
    print("\n[Synchronization Packet]")
    print("Spacecraft ID: {}".format(scid))
    print("Minor Frame Counter: {}".format(frame_cnt))


def message_handler(packet):
    if fletcher_decode(packet) != 0:
            return
    packet_no = (packet[1] & 0xF) + 1
    total_packets = (packet[1] & 0xF0) >> 4
    message = packet[2:10]
    message.reverse()
    message = bytes(message)

    print("\n[Message Packet]")
    print("Packet Number: {}/{}".format(packet_no, total_packets))
    print("Message: {}".format(ba.hexlify(message)))


def uplink_handler(packet):
    if fletcher_decode(packet) != 0:
            return
    packet_no = (packet[1] & 0xF) + 1
    total_packets = (packet[1] & 0xF0) >> 4
    channels = packet[3:10]
    channels.reverse()
    nibbles = []
    for byte in channels:
        nibbles.append((byte & 0xF0) >> 4)
        nibbles.append(byte & 0xF)
    nibbles = nibbles[2:]
    channels = []
    for channel in mi.grouper(3, nibbles):
        num = (channel[0] << 8) + (channel[1] << 4) + channel[2]
        if(num != 0):
            channels.append(num)
    channels = np.array(channels)

    print("\n[Uplink Channel Packet]")
    print("Packet Number: {}/{}".format(packet_no, total_packets))
    for channel in channels:
            print("{:.4f}MHz".format(channel * 0.0025 + 148), end=' ')
    print('')


def downlink_handler(packet):
    if fletcher_decode(packet) != 0:
        return
    packet_no = (packet[1] & 0xF) + 1
    total_packets = (packet[1] & 0xF0) >> 4
    channels = packet[2:10]
    channels.reverse()
    nibbles = []
    for byte in channels:
        nibbles.append((byte & 0xF0) >> 4)
        nibbles.append(byte & 0xF)
    nibbles.pop(0)
    channels = []
    for channel in mi.grouper(3, nibbles):
        num = (channel[0] << 8) + (channel[1] << 4) + channel[2]
        if (num <= 320) and (num >= 80):
            channels.append(num)
    channels = np.array(channels)

    print("\n[Downlink Channel Packet]")
    print("Packet Number: {}/{}".format(packet_no, total_packets))
    print("Frequencies: ", end='')
    for channel in channels:
        print("{:.4f}MHz".format(channel * 0.0025 + 137), end=' ')
    print('')


def epemeris_hander(packet):
    # Ephemeris Packet
    try:
        full_pack = packet + pending_packets.popleft()
    # If decoder is interrupted, we cant' grab the next packet
    except IndexError:
        return
    if fletcher_decode(full_pack) != 0:
        return
    scid = "FM-{}".format(full_pack[1])

    # GPS Time is represented as # of weeks since the GPS epoch,
    # and seconds since the beginning of that week
    week = (full_pack[-3] << 8) + full_pack[-4]
    seconds = (full_pack[-5] << 16) + (full_pack[-6] << 8) + full_pack[-7]

    orbit = full_pack[2:17]

    # Retrieve Binary Value for Each Coordinates,
    # then convert to physical value
    posX = orbit[0] + (orbit[1] << 8) + ((orbit[2] & 0xF) << 16)
    posX = ((2 * posX * 8378155) / 1048576 - 8378155) / 1000
    posY = (orbit[2] >> 4) + (orbit[3] << 4) + (orbit[4] << 12)
    posY = ((2 * posY * 8378155) / 1048576 - 8378155) / 1000
    posZ = orbit[5] + (orbit[6] << 8) + ((orbit[7] & 0xF) << 16)
    posZ = ((2 * posZ * 8378155) / 1048576 - 8378155) / 1000

    # Retrieve Binary Value for Each Pos, then convert to physical value
    velX = (orbit[7] >> 4) + (orbit[8] << 4) + (orbit[9] << 12)
    velX = ((2 * velX * 7700) / 1048576 - 7700) / 1000
    velY = orbit[10] + (orbit[11] << 8) + ((orbit[12] & 0xF) << 16)
    velY = ((2 * velY * 7700) / 1048576 - 7700) / 1000
    velZ = (orbit[12] >> 4) + (orbit[13] << 4) + (orbit[14] << 12)
    velZ = ((2 * velZ * 7700) / 1048576 - 7700) / 1000

    # Orbit Radius minus Earth's Radius
    height = math.sqrt(pow(posX, 2) + pow(posY, 2) + pow(posZ, 2)) - 6378.15

    # Magnitude of Velocity
    vel_orbit = math.sqrt(pow(velX, 2) + pow(velY, 2) + pow(velZ, 2))

    # ECEF to Lat, Lon, and Altitude
    lat, lon, alt = ecef2lla(posX * 1000, posY * 1000, posZ * 1000)

    print("\n[Ephemeris Packet]")
    print("Spacecraft ID: {}".format(scid))
    print("GPS Date: {}".format(gps2date(week, seconds)))
    # print("Position: X = {0:.3f}km Y = {1:.3f}km Z = {2:.3f}km"
    #      .format(posX, posY, posZ))
    print("Position: Latitude = {0:.3f}° Longitude = {1:.3f}° "
          "Altitude = {2:.3f}km".format(lat, lon, alt / 1000))
    print("Velocity: X = {0:.3f}km/s Y = {1:.3f}km/s Z = {2:.3f}km/s"
          .format(velX, velY, velZ))
    print("Height = {0:.3f}km Orbital Velocity = {1:.3f}km/s"
          .format(height, vel_orbit))


def element_handler(packet):
    if fletcher_decode(packet) != 0:
            return
    scid = "FM-{}".format(packet[1])
    mean_anomaly = (packet[5] << 16) + (packet[4] << 8) + packet[3]
    mean_anomaly = 360.0 * (mean_anomaly / 16777215)

    mean_motion = (packet[9] << 24) + (packet[8] << 16) +\
                  (packet[7] << 8) + packet[6]
    mean_motion = 15.00000106 * (mean_motion / 4294967295)

    print("\n[Element Packet]")
    print("Spacecraft ID: {}".format(scid))
    print("Mean Anomaly: {:.4f}°".format(mean_anomaly))
    print("Mean Motion: {:.4f} revs/day".format(mean_motion))


def udp_input(address, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((address, port))

    while True:
        data, addr = sock.recvfrom(4800)
        pending_bits.extend(data)


def file_input(filename):
    with open(filename, mode='rb') as f:
        fileData = f.read()
    for byte in fileData:
        pending_bits.append(int(byte))


def framer():
    frame = []
    # Orbcomm Syncword 0x65A8F9 (LSB First)
    sync = [1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1,
            0, 1, 0, 1, 1, 0, 0, 1, 1, 1, 1, 1]

    while True:
        if len(pending_bits) > 0:
            if len(frame) == 4800:
                frame.pop(0)
            frame.append(pending_bits.popleft())
            if frame[0:24] == sync:
                pending_frames.append(list(frame))
        else:
            time.sleep(0.25)


def packetizer():
    pow2 = [1, 2, 4, 8, 16, 32, 64, 128]
    while True:
        if len(pending_frames) > 0:
            frame = pending_frames.popleft()
            frame_bytes = bytearray()
            # Convert every 8 bits to a byte (LSB First)
            for octet in mi.grouper(frame, 8):
                frame_bytes.append(np.dot(list(octet), pow2))
            for packet in mi.grouper(frame_bytes, 12):
                pending_packets.append(list(packet))
        else:
            time.sleep(0.25)


def packet_parse():
    packet_enabled = {"synch": False, "msg": False, "up": True,
                      "down": True, "ncc": True, "fill": True,
                      "ephem": True, "elems": True}
    packet_types = {"synch": 0x65, "msg": 0x1A, "up": 0x1B,
                    "down": 0x1C, "ncc": 0x1D, "fill": 0x1E,
                    "ephem": 0x1F, "elems": 0x22}
    while True:
        if len(pending_packets) > 0:
            packet = pending_packets.popleft()
            if packet[0] == packet_types['synch'] and packet_enabled['synch']:
                synch_handler(packet)
            if packet[0] == packet_types['msg'] and packet_enabled['msg']:
                message_handler(packet)
            if packet[0] == packet_types['up'] and packet_enabled['up']:
                uplink_handler(packet)
            if packet[0] == packet_types['down'] and packet_enabled['down']:
                downlink_handler(packet)
            if packet[0] == packet_types['ephem'] and packet_enabled['ephem']:
                epemeris_hander(packet)
            if packet[0] == packet_types['elems'] and packet_enabled['elems']:
                element_handler(packet)
        else:
            time.sleep(0.25)


def main():
    address = "127.0.0.1"
    port = 10000
    # filename = "symbolsfm.bin"

    t_udp = threading.Thread(target=udp_input,
                             args=(address, port))
    # t_file = threading.Thread(target=file_input,
    #                          args=([filename]))
    t_framer = threading.Thread(target=framer, args=())
    t_packet = threading.Thread(target=packetizer, args=())
    t_parse = threading.Thread(target=packet_parse, args=())

    t_udp.start()
    # t_file.start()
    t_framer.start()
    t_packet.start()
    t_parse.start()
    t_udp.join()


if __name__ == '__main__':
    main()
