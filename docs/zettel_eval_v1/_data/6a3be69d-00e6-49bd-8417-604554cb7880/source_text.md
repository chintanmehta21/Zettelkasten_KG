## Overview
- This repository contains the data and R code for The Economist's Big Mac index.

### Core argument
- This repository contains the data and R code for The Economist's Big Mac index.

### Architecture
- The core logic resides in a Jupyter Notebook (`Big Mac data generator.ipynb`) and a standalone R script (`data-generator-v2.R`), which process various source data inputs (Big Mac prices, exchange rates, GDP/population) to generate three primary output CSV files: `big-mac-raw-index.csv`, `big-mac-adjusted-index.csv`, and `big-mac-full-index.csv`.

### Stack
- Jupyter Notebook, R, tidyverse, data.table.

## Features and modules

### Overview
- TheEconomist/big-mac-data contains the data and R code for The Economist's Big Mac index.
- The codebase is primarily a Jupyter Notebook (99.2% of the codebase).
- Data can be downloaded from the releases page in CSV or Excel format.
- In July 2022, the methodology was updated: the US price is now sourced directly from McDonald's, and the GDP-adjusted index adjusts GDP per person by the difference in Big Mac prices.
- This methodology change means the historical GDP-adjusted series may change over time as the IMF refines its data.

### Architecture / Modules
- The repository's core logic is implemented in `Big Mac data generator.ipynb` (Jupyter Notebook) and `data-generator-v2.R` (standalone R script).
- These scripts process source data to generate three output files: `big-mac-raw-index.csv`, `big-mac-adjusted-index.csv`, and `big-mac-full-index.csv`.
- The codebook defines variables including raw and adjusted indices relative to USD, EUR, GBP, JPY, and CNY.
- The Jupyter Notebook and R script may produce minor rounding differences.

### Public API / Interfaces
- The primary user-facing components are the data generation scripts and the resulting data files.
- Public surface: `Big Mac data generator.ipynb`, `data-generator-v2.R`, `big-mac-raw-index.csv`, `big-mac-adjusted-index.csv`, `big-mac-full-index.csv`.

### Operational Guidance
- To run the data generation code, users need to install Python 3, Jupyter, R, IRkernel, and the R packages `tidyverse` and `data.table`.
- Installation instructions are provided for Mac and Ubuntu, but are missing for Windows.
- Usability signals: pip install jupyter, install.packages("IRkernel"), install.packages("tidyverse"), install.packages("data.table").

### Uncertainties / Caveats
- Frequent delays in updating the repository's data compared to The Economist's website (issues #39, #38, #37, #32), leading some to believe the project is abandoned (issue #38).
- The official website is now behind a paywall (issue #35).
- Users have reported data inaccuracies for countries like Turkey, Lebanon, and Mexico (issues #28, #27, #26).
- There are requests for methodology clarifications (issue #31) and considerations for product size changes (issue #33).
- Suggestions for technical improvements include adding a devcontainer, Docker support, or CI (issues #34, #15, #16).
- A pull request (#40) aims to add data visualization and an API.