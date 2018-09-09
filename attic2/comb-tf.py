#!/usr/bin/python3
from io import BytesIO
from base64 import b64encode

from matplotlib.pyplot import imshow
import matplotlib.pyplot as plt

import numpy as np

import scipy.signal as sps

from time import time
#from PIL import Image

import tensorflow as tf
import sys

import os

infd = sys.stdin.buffer
outfd = None
#outfd = open('pipe3.rgb', 'wb')

# This follows the default scale in lddecodercuda
minire = -60
maxire = 140

hz_ire_scale = (9300000 - 8100000) / 100
minn = 8100000 + (hz_ire_scale * -60)

out_scale = 65534.0 / (maxire - minire)

in_scale = out_scale
in_minire = -60

def RawToIRE(data):
    return (np.float32(data) / in_scale) + in_minire

def IREToRaw(data):
    return np.uint16((data - minire) * out_scale)

def cfoutput_torgb(output):
    r = output[3].reshape((505, 844))
    g = output[4].reshape((505, 844))
    b = output[5].reshape((505, 844))

    rgbArray = np.zeros((505,844,3), 'uint8')
    rgbArray[...,0] = np.clip(r, 0, 100) * 2.55
    rgbArray[...,1] = np.clip(g, 0, 100) * 2.55
    rgbArray[...,2] = np.clip(b, 0, 100) * 2.55

    im = Image.fromarray(rgbArray)
    im = im.resize((844, 505))

    #    imshow(np.asarray(im))

    b = BytesIO()
    im.save(b, format='png')
    return IPython.display.Image(b.getvalue())

ntscimg_shape = [1, 505, 844, 1]

def conv1d(data, b, _padding='SAME'):
    #tf_var = tf.Variable(np.array(b).reshape(1, len(b), 1, 1), dtype=tf.float32)
    #tf_var.initializer.run()

    return tf.nn.conv2d(data, b, strides=[1,1,1,1], padding=_padding)

# carry out phase inversion based off predefined stitches
def phaseinvert(c, stitches1, stitches2):
    csplit = tf.dynamic_partition(c, partition, 2)
    csplit[1] *= -1 
    return tf.reshape(tf.dynamic_stitch([stitches1, stitches2], csplit), ntscimg_shape)

# Used to put I+Q back together to remove C from Y, and to double IQ for output by repeating data1
def InterleaveX(data1, data2):
    wide_pre = tf.dynamic_stitch([stitchIQ[0], stitchIQ[1]], [tf.transpose(data1), tf.transpose(data2)])
    return tf.reshape(tf.transpose(wide_pre), ntscimg_shape)

def buildmasks():
    # Create I and Q mask images
    IQmask_p = np.zeros((505, 844), dtype=np.float32)

    for i in range(0, 844, 4):
        # We can transpose the array and set all values of a column at once
        IQmask_p.T[i + 0] = 1
        IQmask_p.T[i + 1] = -1
        IQmask_p.T[i + 2] = -1
        IQmask_p.T[i + 3] = 1

    IQmask = tf.Variable(IQmask_p.reshape(ntscimg_shape), dtype=tf.float32)
    IQmask.initializer.run()

    partIQp = np.zeros((844), dtype=np.int32)

    for i in range(0, 844, 2):
        # We can transpose the array and set all values of a column at once
        partIQp[i] = 0
        partIQp[i + 1] = 1

    partIQ = tf.Variable(partIQp.reshape([1, 844]), dtype=tf.int32)
    partIQ.initializer.run()
    
    stitchIQ = []
    for i in [0, 1]:
        stitchp = np.where(partIQp == i)[0]

        stitchIQ.append(tf.Variable(stitchp.reshape([1, 422]), dtype=tf.int32))
        stitchIQ[-1].initializer.run()

    return IQmask, partIQ, stitchIQ

# Variables useful for comb filtering/YC splitting
def buildfilters():
    
    vshift = {}
    hshift = {}

    for vd in [-4, -2, 2, 4]:
        vshift[vd] = np.zeros((505), dtype=np.int32)
    
    vshift[-4][0:501] = range(4, 505)
    vshift[-2][0:503] = range(2, 505)
    vshift[2][2:505] = range(0, 503)
    vshift[4][4:505] = range(0, 501)

    for vd in [-8, -4, -2, -1, 1, 2, 4, 8]:
        hshift[vd] = np.zeros((844), dtype=np.int32)
    
    hshift[-8][0:836] = range(8, 844)
    hshift[-4][0:840] = range(4, 844)
    hshift[-2][0:842] = range(2, 844)
    hshift[-1][0:843] = range(1, 844)
    hshift[1][1:844] = range(0, 843)
    hshift[2][2:844] = range(0, 842)
    hshift[4][4:844] = range(0, 840)
    hshift[8][8:844] = range(0, 836)
    
    fsc = 315.0 / 88.0
    ChromaLPFp = sps.firwin(17, [1.5 / fsc])
    ChromaLPF = tf.Variable(ChromaLPFp.reshape(1, 17, 1, 1), dtype=np.float32)
    ChromaLPF.initializer.run()

    #YC_LPF = tf.Variable(np.array([.5,-1,.5]).reshape(1, 1, 3, 1), dtype=np.float32)
    #YC_LPF.initializer.run()

    return vshift, hshift, ChromaLPF#, YC_LPF


# Colorspace conversion
def YIQtoRGB(Y, I, Q):
    R = Y + ( .956 * I) + (.621 * Q)
    G = Y - ( .272 * I) - (.647 * Q)
    B = Y - (1.106 * I) + (1.703 * Q)

    return R, G, B

def hsplit(x):
    # break out I and Q - note that horizontal splits seem to require transposition!
    c_fixedlevelsT = tf.transpose(x)
    partedIQ = tf.dynamic_partition(c_fixedlevelsT, partIQ, 2)

    # detranspose the split IQ data and shape into half-width image
    Q = tf.reshape(tf.transpose(partedIQ[0]), [1, 505, 422, 1])
    I = tf.reshape(tf.transpose(partedIQ[1]), [1, 505, 422, 1])

    return I, Q
    
# rough YC split, with level inversions so I and Q have locked phase
def YCsplit(x, yc_lpf):
    combed = tf.nn.conv2d(x, yc_lpf, strides=[1,1,1,1], padding='SAME')
    c_fixedlevels = phaseinvert(combed, stitches1, stitches2) * IQmask

    return c_fixedlevels # hsplit(c_fixedlevels)

def C_LPF(C, clpf):
    I, Q = hsplit(C)
    If, Qf = conv1d(I, clpf), conv1d(Q, clpf)
    
    return InterleaveX(Qf, If)

def do_hshift(img, amount):
    shape = img.get_shape()
    img_rs = tf.reshape(img, shape[1:3])
    
    img_tshift = tf.gather(tf.transpose(img_rs), hshift[amount])
    img_shift = tf.transpose(img_tshift)
    
    return tf.reshape(img_shift, shape)

# idea from https://stackoverflow.com/questions/35769944/manipulating-matrix-elements-in-tensorflow/35780087#35780087
def mask(data, mask, width = 844):
    datars = tf.reshape(data, [505, width, 1])
    dzero = tf.zeros_like(datars)
    
    x = tf.select(mask, datars, dzero)

    return tf.reshape(x, [1, 505, width, 1])

mask2d_up = np.full(505, True, dtype=np.bool)
mask2d_up[0:4] = False

mask2d_down = np.full(505, True, dtype=np.bool)
mask2d_down[-4:] = False

rgbArray = []

gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=.2)
with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:
#if True:
    x = tf.placeholder(tf.float32, ntscimg_shape)
    partition = tf.placeholder(tf.int32, [1, 505])
    stitches1 = tf.placeholder(tf.int32)
    stitches2 = tf.placeholder(tf.int32)
    RGBout = tf.placeholder(tf.uint8, [505, 844, 3])
    
    #x2 = mask(x, 844)

    YC_LPFh = tf.Variable(np.array([.5,-1,.5]).reshape(1, 3, 1, 1), dtype=np.float32)
    YC_LPFh.initializer.run()

    # These need to be done inside the session
    IQmask, partIQ, stitchIQ = buildmasks()
    vshift, hshift, ChromaLPF = buildfilters()

    # Get a 1D Y/C split and do LPF on I+Q
    Cs = YCsplit(x, YC_LPFh)
    C = C_LPF(Cs, ChromaLPF)

    CFup = tf.Variable(np.array([.5, 0, .5, 0, 0]).reshape(5, 1, 1, 1), dtype=np.float32)
    CFup.initializer.run()
    
    Cup = tf.nn.conv2d(C, CFup, strides=[1,1,1,1], padding='SAME')    
    Cupa = tf.abs((Cup + do_hshift(Cup, 1)) / 2)

    CFdown = tf.Variable(np.array([0, 0, .5, 0, .5]).reshape(5, 1, 1, 1), dtype=np.float32)
    CFdown.initializer.run()
    
    Cdown = tf.nn.conv2d(C, CFdown, strides=[1,1,1,1], padding='SAME')
    Cdowna = tf.abs((Cdown + do_hshift(Cdown, 1)) / 2)

    Cbase = .25
    Cmax = 3

    Cdiff2 = Cup - Cdown
    Cdiff1 = Cdown - Cup
    Kup = tf.clip_by_value((tf.abs((Cup - C) - Cdiff2) - Cbase) / Cmax, 0, 1)
    Kdown = tf.clip_by_value((tf.abs((Cdown - C) - Cdiff1) - Cbase) / Cmax, 0, 1)
    
    K1d = tf.clip_by_value(1 - Kup - Kdown, 0, 1)
    
    Ca = ((Cup * Kup) + (Cdown * Kdown) + (C * K1d)) / (Kup + Kdown + K1d)

    I, Q = hsplit(Ca)
    # Wrapup phase

    C_afterproc = InterleaveX(Q, I) # re-merge I+Q
    c_fory = phaseinvert(C_afterproc * IQmask, stitches1, stitches2) # re-invert phase and levels to match C-in-Y

    # Compute final Y
    Y = x + c_fory

    # Double I and Q width 
    Iwide, Qwide = InterleaveX(I, I), InterleaveX(Q, Q)
    
    Yclip = tf.image.crop_to_bounding_box(tf.reshape(Y, (505, 844, 1)), 25, 80, 480, 744)
    Iclip = tf.image.crop_to_bounding_box(tf.reshape(Iwide, (505, 844, 1)), 25, 80, 480, 744)
    Qclip = tf.image.crop_to_bounding_box(tf.reshape(Qwide, (505, 844, 1)), 25, 80, 480, 744)
    
    cmult = np.sqrt(2.0)
    R, G, B = YIQtoRGB(Yclip, Iclip * cmult, Qclip * cmult)
    
    # 'front end' begins here
    
    
    #infd = open('/home/cpage/ld-decode/he010-180_190.tbc', 'rb')
    #outfd = open('testout.rgb', 'wb')
    
    rgbArray = np.zeros((480,744,3), 'uint8')
    
    fc = 0
    
    while True:
        try:
            indata = infd.read((844 * 505 * 2))
        except:
            indata = None
            
        if indata is None or len(indata) < (844 * 505 * 2):
            print('FAIL:', len(indata))
            break
            
        data = np.fromstring(indata, 'uint16', len(indata)//2)

        rowphase = data[:505*844].reshape(505,844)[:,0] == 32768
        data1 = RawToIRE(data[:505*844])

        in_partition = np.int32(rowphase).reshape(1,505)
        in_stitches1 = np.where(in_partition == 0)[1]
        in_stitches2 = np.where(in_partition == 1)[1]

        output = sess.run([Y, Iwide, Qwide, R, G, B], feed_dict={x: data1.T.reshape(1,505,844,1), 
                                                              partition: in_partition,
                                                              stitches1: in_stitches1,
                                                              stitches2: in_stitches2})
        
        Rout = output[3].reshape((480, 744))
        Gout = output[4].reshape((480, 744))
        Bout = output[5].reshape((480, 744))

        rgbArray[...,0] = np.clip(Rout, 0, 100) * 2.55
        rgbArray[...,1] = np.clip(Gout, 0, 100) * 2.55
        rgbArray[...,2] = np.clip(Bout, 0, 100) * 2.55
        
        fc += 1
        print("FRAMEout ", fc)
        
        os.write(3, rgbArray.reshape(744 * 480 * 3))
        
        #exit(0)
