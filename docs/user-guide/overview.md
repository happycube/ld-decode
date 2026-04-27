# Overview

The purpose of ld-decode is to take sampled RF information from a captured LaserDisc and convert it into a TBC (Time Base Corrected) file along with a SQLite metadata file that details frame-by-frame the contents of the TBC.

RF information is captured directly from the laser pick-up inside the LaserDisc player.  This is effectively an optical copy of the LaserDisc's track which is the 14km spiral of information encoded into the disc's surface including all the scratches, damage and other degradation.  In addition, the spinning LaserDisc (like all physical media) suffers from jittering, loss of tracking, skipping and a number of other issues that can affect the quality of the capture.

The raw LaserDisc RF must be demodulated from the captured FM signal and filtered into multiple parts such as video, analogue audio and EFM data. These parts are then framed (a process often called 'clock recovery') and then passed through a time-base correction (TBC) process which attempts to remove errors temporal errors caused by the mechanical nature of a LaserDisc player during capture.

# Obtaining a LaserDisc RF capture

The process of modifying LaserDisc players, preparing them for capture and setting up the required equipment is very technical and involved.  The exact techniques are covered by the various solutions that provide capture capabilities such as the Domesday Duplicator.  The capture of LaserDisc RF is out of scope for this documentation; please refer to the documentation provided by your capture equipment provider.  For example, if you used the Domesday Duplicator, you will find [extensive documentation available](https://simoninns.github.io/DomesdayDuplicator-docs/){target="_blank"}.

To begin with it is recommended that you simply download a pre-made RF copy of a LaserDisc and use that to experiment with. This is important as, having a known-good capture, is key to learning about the ld-decode process.

You can find a number of LaserDisc captures (from calibrated and tested players) on the [Internet Archive](../misc/disc-images.md).

To begin with, download a copy of the [Pioneer GGV1069 NTSC Test and Calibration disc](https://archive.org/details/pioneer-ggv-1069-cav-ntsc-side-1){target="_blank"}

# Decoding a disc

Now you have a copy of a LaserDisc make sure you have installed a copy of ld-decode on your machine.  The following command should provide you with a version string.

```
ld-decode --version
```

If this command produces and error (or the command cannot be found) please revisit the installation section of this documentation and ensure you have correctly installed ld-decode onto your machine.

In order to decode the LaserDisc you will first need to determine where the actual start of the disc is.  As a real player has to spin up and seek before playing, there can be a lot of 'random' samples that can confuse the decoding process.  There are a number of techniques to deal with this, but the simplest is to ask ld-decode to jump a safe distance into the sample and report the frame number/timecode it finds.  For example:

```
ld-decode ./input/GGV1069_CAV_NTSC_side1_dup1_2019-09-12_21-11-38.ldf ./output/ggv1069 --start 600 --length 1
```

Will show something similar to the following output:

```
Frame 1/1: File Frame 600: CAV Frame #318                                       
Completed: saving JSON and exiting.
Took 18.82 seconds to decode 1 frames (2.67 FPS post-setup)
```

Note the CAV frame 318.  This means at the specified start location of 600 (which is basically 600 frames worth of data into the sample) the read frame number is 318.  So 600-318 = 282.  So 282 is the approximate start location.  We can test this with:

```
ld-decode ./input/GGV1069_CAV_NTSC_side1_dup1_2019-09-12_21-11-38.ldf ./output/ggv1069 --start 282 --length 1
```

Here is the output of this process:

```
ld-decode ./input/GGV1069_CAV_NTSC_side1_dup1_2019-09-12_21-11-38.ldf ./output/ggv1069 --start 282 --length 1

Unable to determine start of field - dropping field
Frame 1/1: File Frame 282: CAV Lead In                                          
Completed: saving JSON and exiting.
Took 2.70 seconds to decode 1 frames (10.50 FPS post-setup)


ld-decode ./input/GGV1069_CAV_NTSC_side1_dup1_2019-09-12_21-11-38.ldf ./output/ggv1069 --start 283 --length 1

Frame 1/1: File Frame 283: CAV Frame #1                                         
Completed: saving JSON and exiting.
Took 2.71 seconds to decode 1 frames (11.57 FPS post-setup)
```

Now we know the correct start offset is 283 frame-lengths into the disc.

To now decode the entire contents of the disc we simply remove the --length switch (or replace 1 with the number of frames required).

That's it!  Once the command has completed you will see a number of files created:

```
ggv1069.efm    - The EFM data (if present)
ggv1069.log    - ld-decodes log output
ggv1069.pcm    - The analogue audio track
ggv1069.tbc    - The actual TBC video file
ggv1069.tbc.db - The SQLite metadata
```

Once you have a TBC file it's time to head over to the [Decode Orc project](https://simoninns.github.io/decode-orc-docs){target="_blank"} for instructions on how to change your TBC back into usable video and audio.

# Next steps

Obviously this is a simple example and, depending on the complexity of the source, there are many other options available from ld-decode.  Please see the rest of this user-guide for more advanced options.