# Big-FISH FISH Image Quantification and Analysis Pypeline

Pre-process and quantify single-molecule Fluorescence *in situ* Hybridisation (smFISH) images with [Big-FISH](https://github.com/fish-quant/big-fish).

## To do

- [ ] Update Cellpose to version 4 (Cellpose-SAM) in the env. Update relevant scripts to use the Cellpose v4 argument syntax.
- [ ] General code hygiene to modularise each steps so they can user-defined. Combine workflow modes into one and make them toggle-able via configuration script based on which modules the user would like to keep. 
- [ ] Implement an option to bring pre-segmented masks without breaking the workflow. 
- [ ] Implement Streamlit web app (optimisation --> handover to batch) ([test/streamlit/](test/streamlit/))
- [ ] Think about making a portable package with streamlit. 


## Installation

1. **Install Miniforge** (provides `conda`): download the installer for your system from [conda-forge.org/download](https://conda-forge.org/download/) and follow the [install instructions](https://github.com/conda-forge/miniforge#install).
   - **Windows:** run the commands below in **Miniforge Prompt** (Start menu).
   - **macOS / Linux:** run them in a new Terminal window.
2. **Get this repository:** [download the ZIP](https://github.com/jefflee1103/bigfish-pypeline/archive/refs/heads/main.zip) and unzip it, or clone it with [Git](https://git-scm.com/downloads):

       git clone https://github.com/JeffLeeLab/bigfish-pypeline.git

3. **Create the environment** (one-off, takes a few minutes):

       cd path/to/bigfish-pypeline
       conda env create -f environment.yml

## Usage

    conda activate bigfish-pypeline
    jupyter lab

Then open the notebook for your workflow ([JupyterLab guide](https://jupyterlab.readthedocs.io/en/stable/getting_started/starting.html)):

| Folder | Workflow |
|-|-|
| [general/](general/) | smFISH spot and cluster quantification |
| [tissue-culture_cells/](tissue-culture_cells/) | smFISH quantification in cultured cells |
| [HCRv3_spot-count/](HCRv3_spot-count/) | HCRv3 spot counts |
| [omero/](omero/) | Parameter optimisation with images from OMERO |
| [posthoc_analysis/](posthoc_analysis/) | Signal-to-noise comparisons |

Cellpose downloads its model weights on first use, so the first segmentation run needs an internet connection.

## Managing the environment

| Task | Command |
|-|-|
| Update after `environment.yml` changes | `conda env update -f environment.yml --prune` |
| List installed packages | `conda list -n bigfish-pypeline` |
| Delete the environment | `conda env remove -n bigfish-pypeline` |

## Resources

- [conda cheat sheet](https://docs.conda.io/projects/conda/en/latest/user-guide/cheatsheet.html)
- [Big-FISH documentation](https://big-fish.readthedocs.io/en/stable/)
- [Cellpose 3 documentation](https://cellpose.readthedocs.io/en/v3.1.1.1/)
