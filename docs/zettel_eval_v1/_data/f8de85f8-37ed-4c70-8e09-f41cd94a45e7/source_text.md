## Overview
- Import AI newsletter #455 reports a 60%+ probability that AI systems will autonomously develop their own successors by late 2028, achieving no-human-involved AI R&D.

### Publication
- Import AI newsletter #455.

### Stance
- The piece adopts a cautionary stance.

### Core argument
- AI systems will be able to autonomously build their own successors—achieving no-human-involved AI R&D—by the end of 2028, with a 60%+ probability.

## Section walkthrough

### The Core Prediction and its Basis
- The author of Import AI newsletter #455 reluctantly posits a 60%+ probability that AI systems will be able to autonomously build their own successors by the end of 2028.
- This prediction implies achieving no-human-involved AI R&D, a milestone in AI development.
- The conclusion is based on public data from sources like arXiv, bioRxiv, and NBER, focusing on the aggregate trend across multiple benchmarks.
- The author acknowledges individual flaws in these benchmarks but emphasizes the overall upward trajectory of AI capabilities.
- A proof-of-concept for a non-frontier model training its successor is expected within a year or two, though full automation is not anticipated in 2026.
- The author's 2028 prediction is tempered by the belief that some human creativity is still needed, with the probability for 2027 stated as 30%.
- If automation does not occur by 2028, it may indicate a fundamental limitation in the current AI paradigm.

### Evidence from Coding and Complex Task Completion
- Evidence for this trend includes AI's rapidly improving capabilities in coding and completing complex, long-duration tasks.
- On the SWE-Bench for real-world GitHub issues, performance has dramatically increased from approximately 2% by Claude 2 in late 2023 to 93.9% by Claude Mythos Preview, effectively saturating the benchmark.
- METR's time horizons plot, which measures the duration of tasks an AI can be 50% reliable at, shows capabilities increasing significantly.
- Capabilities have risen from approximately 30 seconds for GPT-3.5 (2022) to approximately 12 hours for Opus 4.6 (2026).
- Forecaster Ajeya Cotra suggests that approximately 100-hour tasks are possible by the end of 2026.
- These advances correlate with the rise of agentic tools, which allow researchers to delegate tasks such as data cleaning and experiment launching to AI.

### AI Mastering Core Scientific Skills for R&D
- AI is also demonstrating mastery of core scientific skills for its own research and development.
- On CORE-Bench, which tests the reproduction of scientific papers, performance jumped from approximately 21.5% in September 2024 (GPT-4o) to 95.5% in December 2025 (Opus 4.5).
- OpenAI's MLE-Bench, designed for Kaggle competitions, saw scores rise from 16.9% in October 2024 (o1 model) to 64.4% in February 2026 (Gemini3).
- These benchmarks indicate AI's growing ability to understand, replicate, and contribute to scientific processes.
- The rapid improvement across these diverse scientific tasks suggests a foundational shift in AI's capacity for independent research.

### AI in Core AI Development Tasks and Meta-Skills
- In kernel optimization, a core AI development task, AI is now used competitively for tasks like generating Triton kernels at Meta and writing kernels for Huawei's Ascend chips.
- On PostTrainBench, which tests fine-tuning smaller models, AI systems like Opus 4.6 and GPT 5.4 achieve scores of 25%-28%, about half the human baseline of 51% as of March/April 2026.
- In an Anthropic task for optimizing LLM training code, speedups increased from 2.9x (Opus 4, May 2025) to 52x (Claude Mythos Preview, April 2026), where a human takes 4-8 hours for a 4x speedup.
- Anthropic has also shown a proof-of-concept where AI agents autonomously developed techniques for an AI safety problem that beat a human baseline.
- Furthermore, AI systems are developing meta-skills, such as managing other AI agents in synthetic teams, indicating coordination capabilities.

### Creativity, Frontier Lab Pursuit, and Profound Implications
- While the author believes AI cannot yet produce radical, paradigm-shifting ideas like the transformer architecture, they argue that most AI progress is methodical engineering work, which AI is becoming adept at automating.
- There are preliminary signs of creativity in math and computer science, such as a Gemini model finding an interesting solution to an Erdos problem and contributing substantially to a new math proof, though these could be exceptions.
- The author concludes that AI can automate vast swathes of AI engineering today, moving beyond mere task execution to active development.
- This goal is explicitly pursued by frontier labs like OpenAI (aiming for an 'automated AI research intern' by September 2026), Anthropic, and DeepMind, as well as heavily funded startups like Recursive Superintelligence ($500m raised) and Mirendil.
- The implications include urgent alignment challenges, as current techniques could fail under recursive self-improvement, with risks like 'faking alignment' and compounding errors (e.g., a 99.9% accurate method degrading to 60.5% after 500 generations).
- Other consequences are a massive productivity multiplier across the economy, creating issues of access inequality and systemic bottlenecks, and the rise of a capital-heavy, human-light 'machine economy' that poses challenges to inequality and governance.

## Closing remarks
- Call to action: The newsletter also discusses the pursuit of this goal by frontier labs and the , urgent implications for alignment and the economy, noting that some human creativity is still believed necessary.