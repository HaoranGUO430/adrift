# adrift

**Stream reasoning over AIS data: detecting irregular tows with a knowledge graph and rules.**

adrift watches vessel traffic around Hawaii and raises an alert when one vessel tows another vessel that normally moves under its own power, such as a fishing boat towed home after an engine failure. This is the visible part of a disabled-vessel incident.

It replays four years of real AIS data (2017–2020) and checks every vessel pair every minute. Alerts escalate from **Low** to **Mid** to **High** as the evidence grows. The results are evaluated against the real incidents labelled in the HawaiiCoast_GT dataset.

On the 37 labelled tows that are visible in the data, adrift detects 32 (86%), with a median delay of 8 minutes for the first alert.

For the motivation, method details, experiments and results, see **[REPORT.md](REPORT.md)**.

## How it works

A tow is defined from physics rather than learned from the labels: the distance between the two vessels stays almost constant, they are close, exactly one vessel stays astern of the other, and both are ships. A tow is irregular when the towed vessel is normally self-propelled (fishing vessel, pleasure craft or industrial vessel).

The project has two pipelines.

### 1. Batch pipeline: analyse the data and fix the rules

`scripts/pipeline_basic_rules.py` processes all four years of AIS data with DuckDB and SQL. This is where the tow definition was developed, tested and frozen, and where the alerts are evaluated against the ground truth.

```
AIS CSV → Clean → 1-min grid → Pairs → Windows → SQL rules → Evaluation
                                                                  ↑
                                                             Ground truth
```

### 2. Stream pipeline: apply the rules to a simulated stream

`scripts/pipeline_stream.py` takes the frozen rules and runs them the way a live system would. Python replays known tows from the raw CSV files minute by minute. DuckDB keeps only a small state, RML turns each minute's windows into RDF, and Kolibrie makes every decision with an ontology and rules. The alerts appear in a desktop app.

```
AIS CSV → Replay → DuckDB (windows) → RML (RDF) → Kolibrie (rules) → Alerts → App
```

Both pipelines use the same thresholds: the stream imports them from the batch scripts. The stream gives exactly the same alerts as the batch pipeline, only 10 minutes later, because it waits for the next AIS message before it interpolates a position.

## Requirements

- Python 3.12 (tested on Windows 11)
- About 25 GB of free disk space (see below)
- Rust, only to build Kolibrie

## Installation

```bash
git clone https://github.com/HaoranGUO430/adrift.git
cd adrift
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Kolibrie is not on PyPI. Build its Python bindings from source (needs [Rust](https://rustup.rs) and, on Windows, the Visual Studio C++ Build Tools):

```bash
git clone https://github.com/StreamIntelligenceLab/Kolibrie.git ../Kolibrie
python -m pip install maturin
cd ../Kolibrie/python
maturin develop --release
```

Kolibrie is only needed for the stream pipeline.

## Data

Download `HawaiiCoast_GT.zip` from [Zenodo](https://doi.org/10.5281/zenodo.8253611) (3.0 GB) and unzip it into the project folder:

```
adrift/
├── HawaiiCoast_GT/
│   ├── AIS_data/            Hawaii_2017_01.csv … Hawaii_2020_12.csv
│   └── incident_data/
├── scripts/
└── …
```

The raw data is not included in this repository.

## Usage

Run the batch pipeline first. It creates the cleaned data, the features, the results and the ground truth, and prints the evaluation:

```bash
python scripts/pipeline_basic_rules.py
```

Then start the stream demo:

```bash
python scripts/pipeline_stream.py
```

The demo does not replay all four years. It replays only four representative tows, each from one hour before to one hour after the labelled incident, in which the alert clearly rises from Low to High and then ends. Choose one and press **Start**. One stream minute is replayed every 0.5 s, so a replay takes 1.5–4.5 minutes. The demo tows are set in `DEMO_INCIDENTS` in `scripts/pipeline_stream.py`.

## Disk space and run time

| | Size |
|---|---|
| Downloaded zip | 3.0 GB (can be deleted after unzipping) |
| Unzipped raw data | about 16 GB |
| Generated data (`clean_data/`, `features/`, `results/`) | about 3.3 GB |
| Python environment | about 0.4 GB |
| Kolibrie source and build | about 0.9 GB |

Plan for about 25 GB of free space during setup, or about 21 GB once the zip is deleted. On a 20-core laptop with 32 GB RAM the batch pipeline takes about 1.5 minutes.

## Repository layout

| Path | Content |
|---|---|
| `scripts/` | Batch steps (`data_cleaning`, `time_grid`, `pair_feature`, `window_feature`, `rules_paired`, `ground_truth`, `evaluation`), stream modules (`stream_*`, `transform_to_rdf`, `kolibrie_rules`), the two pipelines and the alert board (`app.py`) |
| `ontology/adrift.ttl` | Vessel classes, window classes and alert levels |
| `rml/` | RML mappings for the vessel registry and the windows |
| `ground_truth/ground_truth.csv` | 38 tows: the labelled tows plus corrections from the incident reports |

## Data and attribution

This project uses the HawaiiCoast_GT dataset by Sandia National Laboratories, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

> Henriksen, A. (2023). *HawaiiCoast_GT: Curated AIS for Hawaii's coast correlated with ground truth incidents* (v1.0) [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.8253611

> Henriksen, A. (2024). Correlating real-world incidents with vessel traffic off the coast of Hawaii, 2017–2020. *Discover Oceans*, 1, 1. https://doi.org/10.1007/s44289-023-00001-6

`ground_truth/ground_truth.csv` is derived from the dataset's incident labels. I added 4 tows from the incident reports and corrected the swapped MMSIs of incidents #127 and #130 (see [REPORT.md](REPORT.md#6-ground-truth-and-evaluation-method)).
## License

The code is released under the [MIT License](LICENSE). `ground_truth/ground_truth.csv` is derived from HawaiiCoast_GT and is shared under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), like the original dataset.

## Use of AI

The method and all code except `scripts/app.py` were designed and written by me; [Claude Code](https://claude.com/claude-code) (Anthropic) helped with debugging. The written documentation and `scripts/app.py` were drafted with Claude Code. I have read, modified and annotated all of the code.
