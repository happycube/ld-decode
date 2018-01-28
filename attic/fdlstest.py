import fdls as fdls

import numpy as np
import scipy.signal as sps
import matplotlib.pyplot as plt

fm = np.array([0, 19.685, 35.4331, 51.1811, 59.0551, 66.9291, 106.299, 389.764])
wmts = np.array([0, 0.1237, .2226, .3216, .3711, .4205, .6679, 2.449])
Am = np.array([.2172, .2065, .1696, .0164, 1.3959, .6734, .3490, .3095])
Th = np.array([0, -.0156, -.0383, 3.0125, 2.3087, .955, .0343, .0031])

fm = fm / 1000

#Th = np.zeros(len(fm))

print(fdls.FDLS(2, 2, wmts, Am = Am, Th = Th))
exit()

