# QA pairs - iter-04

## q1: According to Andrej Karpathy, what are the two main stages in the development of a large language model, and what does each stage accomplish?

**Answer:** According to Andrej Karpathy, the development of a large language model (LLM) involves a two-stage process: pre-training and fine-tuning [id="yt-andrej-karpathy-s-llm-in"].

The first stage, **pre-training**, involves learning a comprehensive model of text by predicting the next token across a massive dataset, which Karpathy likens to creating a "blurry JPEG of the web" [id="yt-andrej-karpathy-s-llm-in"]. This computationally intensive process ingrains grammar, facts, and reasoning abilities, resulting in a "document completer" base model that continues text statistically but does not inherently follow instructions [id="yt-andrej-karpathy-s-llm-in"].

The second stage, **fine-tuning**, creates an assistant model by aligning the base model with human intent to be a helpful and harmless agent [id="yt-andrej-karpathy-s-llm-in"]. This stage uses a smaller, high-quality dataset of prompt-response pairs for Supervised Fine-Tuning (SFT) and often includes Reinforcement Learning from Human Feedback (RLHF) or Constitutional AI [id="yt-andrej-karpathy-s-llm-in"]. The outcome is an instruction-following assistant model, such as ChatGPT, where its "personality" and helpfulness are crafted [id="yt-andrej-karpathy-s-llm-in"].

- retrieved: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- reranked: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- cited: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']

## q2: What architectural change in the transformer enabled it to scale far beyond previous sequence models like RNNs and LSTMs?

**Answer:** The Transformer architecture enabled unprecedented scaling by replacing sequential recurrence, found in older models like Recurrent Neural Networks (RNNs), with a parallelizable self-attention mechanism [id="yt-transformer-architecture"]. This non-sequential design allows for significant parallelization during training, addressing the bottlenecks and slow processing inherent in RNNs, which were limited by compressing prior context into a single hidden state vector at each step [id="yt-transformer-architecture"]. This shift from sequential processing to parallel self-attention was a fundamental breakthrough, enabling the training of vastly larger models [id="yt-transformer-architecture"].

- retrieved: ['yt-transformer-architecture']
- reranked: ['yt-transformer-architecture']
- cited: ['yt-transformer-architecture']

## q3: How does Karpathy distinguish Software 2.0 from Software 1.0, and how does the development cycle change between them?

**Answer:** Andrej Karpathy distinguishes Software 1.0 as classical programming where humans write explicit instructions using languages like Python or C++, with its program space limited by human design [id="yt-software-1-0-vs-software"]. In contrast, Software 2.0 is an approach where a program's skeleton, such as a neural network architecture, is optimized on large datasets, and the specific program is discovered through this optimization process as learned weights [id="yt-software-1-0-vs-software"]. Software 2.0 excels at complex tasks difficult for humans to program directly, like computer vision, speech recognition, machine translation, and game playing (e.g., AlphaGo) [id="yt-software-1-0-vs-software"].

The development cycle fundamentally changes with Software 2.0. The programmer's role shifts from writing and debugging code to being a "teacher" or "data curator" [id="yt-software-1-0-vs-software"]. Core tasks now involve collecting, cleaning, and meticulously labeling massive datasets [id="yt-software-1-0-vs-software"]. If a Software 2.0 system produces an error, the solution is not to modify the code but to augment the dataset with more labeled examples of the failure case, forming an iterative loop of data curation followed by model retraining [id="yt-software-1-0-vs-software"].

- retrieved: ['yt-software-1-0-vs-software']
- reranked: ['yt-software-1-0-vs-software']
- cited: ['yt-software-1-0-vs-software']

## q4: What is Yann LeCun's main critique of auto-regressive large language models, and what alternative architecture does he propose?

**Answer:** Yann LeCun argues that auto-regressive large language models (LLMs) are fundamentally limited in achieving human-level intelligence because their architecture focuses on next-token prediction [id="yt-lecun-s-vision-human-lev"]. He asserts that these models are restricted to reactive "System 1" thinking, which prevents them from performing true reasoning, planning, or developing an internal world model [id="yt-lecun-s-vision-human-lev"]. LeCun attributes hallucinations and unreliable multi-step reasoning to this architectural flaw, which he believes cannot be resolved by simply scaling the models [id="yt-lecun-s-vision-human-lev"]. Additionally, a finite amount of high-quality training text creates a data bottleneck, limiting their scaling potential [id="yt-lecun-s-vision-human-lev"].

As an alternative, LeCun proposes a modular "Objective-Driven AI" architecture, which is based on Joint Embedding Predictive Architectures (JEPA) [id="yt-lecun-s-vision-human-lev"]. This architecture is designed for reasoning, planning, and building internal world models, and it includes a Perception Module for sensory input and a World Model that simulates dynamics using a JEPA-style approach [id="yt-lecun-s-vision-human-lev"]. JEPA is considered a more efficient and effective alternative for learning world models compared to generative models [id="yt-lecun-s-vision-human-lev"].

- retrieved: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- reranked: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- cited: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']

## q5: Why does the popular perception of programming get it wrong, and what skill is most important in the actual programming workflow?

**Answer:** The popular perception of programming as rapid, flawless typing is inaccurate [id="yt-programming-workflow-is"]. Instead, the actual process is an iterative cycle primarily centered on debugging, where a significant amount of time is dedicated to diagnosing and fixing errors using external resources, rather than writing new code [id="yt-programming-workflow-is"]. Consequently, the most important skill in programming is not typing speed, but rather a methodical problem-solving approach that heavily relies on searching for and applying existing solutions [id="yt-programming-workflow-is"].

- retrieved: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
- reranked: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
- cited: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
