import numpy as np
import more_itertools as mi
import binascii as ba
import datetime as dt
import math


def raw2frames(data, sync, length):
    locations = []
    frames = []
    synclen = len(sync)
    for loc in (i for i, ele in enumerate(data) if ele == sync[0]):
        if data[loc:loc + synclen] == sync:
            locations.append(loc)
    for idx in locations:
        frames.append(data[idx:idx + length])
    if len(frames[-1]) < length:
        frames.pop()
    return frames


def divide_chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]


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


filename = "symbolsfm10.bin"
packet_types = {"synch": 0x65, "message": 0x1A, "uplink": 0x1B,
                "downlink": 0x1C, "ncc": 0x1D, "fill": 0x1E,
                "ephemeris": 0x1F, "elements": 0x22}

with open(filename, mode='rb') as f:
    fileData = f.read()

bits = []
for byte in fileData:
    if byte == 0:
        bits.extend([0])
    if byte == 1:
        bits.extend([1])


sync = [1, 0, 1, 0] + [0, 1, 1, 0 + [0, 0, 0, 1]\
      +[0,1,0,1]+[1,0,0,1]+[1,1,1,1]
frames = raw2frames(bits, sync, 4800)


data = np.array(frames)


frames_bytes = []
for frame in frames:
    fb = bytearray()
    for octet in mi.grouper(8, frame):
        fb.append(np.dot(list(octet),[1,2,4,8,16,32,64,128]))
    frames_bytes.append(fb)

packets = []
for frame in frames_bytes:
    packets.extend(divide_chunks(frame,12))

for i,packet in enumerate(packets):
    # Synchronization Packet
    if packet[0] == packet_types["synch"]:
        if fletcher_decode(packet) != 0:
            continue
        scid = "FM-{}".format(packet[3])
        frame_cnt = (packet[6] & 0xF0)>>4
        
        print("\n[Synchronization Packet]")
        print("Spacecraft ID: {}".format(scid))
        print("Minor Frame Counter: {}".format(frame_cnt))

    # Message Packet
    if packet[0] == packet_types["message"]:
        if fletcher_decode(packet) != 0:
            continue
        packet_no = (packet[1] & 0xF) + 1
        total_packets = (packet[1] & 0xF0) >> 4
        message = packet[2:10]
        message.reverse()

        print("\n[Message Packet]")
        print("Packet Number: {}/{}".format(packet_no,total_packets))
        print("Message: {}".format(ba.hexlify(message)))

    # Uplink Channel Packet
    if packet[0] == packet_types["uplink"]:
        if fletcher_decode(packet) != 0:
            continue
        packet_no = (packet[1] & 0xF) + 1
        total_packets = (packet[1] & 0xF0) >> 4
        channels = packet[3:10]
        channels.reverse()
        nibbles = []
        for byte in channels:
            nibbles.append((byte & 0xF0) >> 4)
            nibbles.append(byte & 0xF)
        nibbles.pop(0)
        nibbles.pop(1)
        channels = []
        for channel in mi.grouper(3,nibbles):
            num = (channel[0]<<8)+(channel[1]<<4)+channel[2]
            if(num != 0) and (num < 190):
                channels.append(num)
        channels = np.array(channels)


        print("\n[Uplink Channel Packet]")
        print((channels*0.0025)+148)
        print("Packet Number: {}/{}".format(packet_no,total_packets))

    # Downlink Channel Packet
    if packet[0] == packet_types["downlink"]:
        if fletcher_decode(packet) != 0:
            continue
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
        for channel in mi.grouper(3,nibbles):
            num = (channel[0]<<8)+(channel[1]<<4)+channel[2]
            if (num <= 320) and (num >= 80):
                channels.append(num)
        channels = np.array(channels)

        print("\n[Downlink Channel Packet]")
        print("Frequencies: ",end='')
        for channel in channels:
            print("{:.4f}MHz".format(channel*0.0025+137),end=' ')
        print('')
        print("Packet Number: {}/{}".format(packet_no,total_packets))

    # Ephemeris Packet
    if packet[0] == packet_types["ephemeris"]:
        full_pack = packet+packets[i+1]
        if fletcher_decode(full_pack) != 0:
            continue
        scid = "FM-{}".format(full_pack[1])

        # GPS Time is represented as # of weeks since the GPS epoch,
        # and seconds since the beginning of that week
        week = (full_pack[-3]<<8) + full_pack[-4]
        seconds = (full_pack[-5]<<16) + (full_pack[-6]<<8) + full_pack[-7]
        
        orbit = full_pack[2:17]

        # Retrieve Binary Value for Each Coordinateos, 
        # then convert to physical value
        posX = orbit[0] + (orbit[1]<<8) + ((orbit[2]&0xF)<<16)
        posX = ((2*posX*8378155)/1048576-8378155)/1000
        posY = (orbit[2]>>4) + (orbit[3]<<4) + (orbit[4]<<12)
        posY = ((2*posY*8378155)/1048576-8378155)/1000
        posZ = orbit[5] + (orbit[6]<<8) + ((orbit[7]&0xF)<<16)
        posZ = ((2*posZ*8378155)/1048576-8378155)/1000

        # Retrieve Binary Value for Each Pos, then convert to physical value
        velX = (orbit[7]>>4) + (orbit[8]<<4) + (orbit[9]<<12)
        velX = ((2*velX*7700)/1048576-7700)/1000
        velY = orbit[10] + (orbit[11]<<8) + ((orbit[12]&0xF)<<16)
        velY = ((2*velY*7700)/1048576-7700)/1000
        velZ = (orbit[12]>>4) + (orbit[13]<<4) + (orbit[14]<<12)
        velZ = ((2*velZ*7700)/1048576-7700)/1000

        # Orbit Radius minus Earth's Radius
        height = math.sqrt(pow(posX,2)+pow(posY,2)+pow(posZ,2)) - 6378.15

        # Magnitude of Velocity
        vel_orbit = math.sqrt(pow(velX,2)+pow(velY,2)+pow(velZ,2))

        print("\n[Ephemeris Packet]")
        print("Spacecraft ID: {}".format(scid))
        print("GPS Date: {}".format(gps2date(week,seconds)))
        print("Position: X = {0:.3f}km Y = {1:.3f}km Z = {2:.3f}km".format(posX,posY,posZ))
        print("Velocity: X = {0:.3f}km/s Y = {1:.3f}km/s Z = {2:.3f}km/s".format(velX,velY,velZ))
        print("Height = {0:.3f}km Orbital Velocity = {1:.3f}km/s".format(height,vel_orbit))

    # Element Packet
    if packet[0] == packet_types["elements"]:
        if fletcher_decode(packet) != 0:
            continue
        scid = "FM-{}".format(packet[1])
        mean_anomaly = (full_pack[5]<<16) + (full_pack[4]<<8) + full_pack[3]
        mean_anomaly = 360.0*(mean_anomaly/16777215)

        mean_motion = (full_pack[9]<<24) + (full_pack[8]<<16) + (full_pack[7]<<8) + full_pack[6]
        mean_motion = 15.00000106*(mean_motion/4294967295)

        print("\n[Element Packet]")
        print("Spacecraft ID: {}".format(scid))
        print("Mean Anomaly: {}".format(mean_anomaly))
        print("Mean Motion: {}".format(mean_motion))

'''
img = Image.fromarray(data * 255)
img = img.convert('RGB')
img.save('test.bmp')
img.save('test.png')
img.show()
'''