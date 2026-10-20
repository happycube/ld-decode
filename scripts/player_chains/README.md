# Player video-chain simulations

Filter simulations behind `docs/technical/player-video-chains.md`, which has the findings,
the sources and the caveats. Component values were read off the players' service-manual
schematics; every response these scripts print is a simulation of those values, not a
manufacturer figure.

| Script | What it simulates |
|---|---|
| `pr7820.py` | Pioneer PR-7820, every stage from the RF equaliser to the TBC output |
| `pr7820_totals.py` | PR-7820 chain totals, de-emphasis divided out, sideband ratios |
| `pr8210.py` | Pioneer PR-8210-A / LD-1100 (VWS-022), RF to de-emphasis and the dropout path |
| `pr8210_tolerance.py` | PR-8210-A main video path over component tolerances |
| `ic_players.py` | Pioneer CLD-S180/CLD-D406 and Panasonic LX-1000U |
| `ladders_early.py` | First pass: CLD-S180 and Sony LDP-1500P ladders (CLD-S180 second LPF superseded) |
| `ldp1500p_allpass.py` | Sony LDP-1500P phase-splitter all-pass stages |
| `ldd_chain.py` | ld-decode's own NTSC chain, factor by factor, through `RFDecode.demodblock` |

Run any of them from the repository root, e.g. `python3 scripts/player_chains/pr7820.py`.
They need numpy and scipy only; `ldd_chain.py` also imports `lddecode`.
