#!/usr/bin/python3

from distutils.core import setup

setup(
    name='ld-decode',
    version='7',

    description='Software defined LaserDisc decoder',
    url='https://github.com/happycube/ld-decode',
    keywords=['video', 'LaserDisc'],
    classifiers=[
        'Environment :: Console',
        'Environment :: X11 Applications :: Qt',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: C++',
        'Programming Language :: Python :: 3',
        'Topic :: Multimedia :: Video :: Capture',
    ],

    packages=['lddecode'],
    scripts=[
        'cx-expander',
        'ld-cut',
        'ld-decode',
        'scripts/ld-compress',
    ],

    # These are just the minimal runtime dependencies for the Python scripts --
    # see the documentation for the full list of dependencies.
    provides=['lddecode'],
    requires=[
        'numba',
        'numpy',
        'scipy',
    ],
)
