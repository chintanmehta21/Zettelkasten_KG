# QA pairs - iter-03

## q1: According to Andrej Karpathy, what are the two main stages in the development of a large language model, and what does each stage accomplish?

**Answer:** According to Andrej Karpathy, the development of a large language model involves two main stages: pre-training and fine-tuning [id="yt-andrej-karpathy-s-llm-in"].

The first stage, **pre-training**, is analogous to building the "kernel" or base model of an operating system [id="yt-andrej-karpathy-s-llm-in"]. Its objective is to learn a comprehensive model of text by predicting the next token across a massive dataset, which ingrains grammar, facts, and reasoning abilities [id="yt-andrej-karpathy-s-llm-in"]. The output of this stage is a "document completer" base model that continues text statistically but does not inherently follow instructions [id="yt-andrej-karpathy-s-llm-in"].

The second stage, **fine-tuning**, creates an assistant model by aligning the base model with human intent to be a helpful and harmless agent [id="yt-andrej-karpathy-s-llm-in"]. This process uses a smaller, high-quality dataset of prompt-response pairs for Supervised Fine-Tuning (SFT) and often includes Reinforcement Learning from Human Feedback (RLHF) or Constitutional AI [id="yt-andrej-karpathy-s-llm-in"]. The result is an instruction-following assistant model, such as ChatGPT, where its "personality" and helpfulness are crafted [id="yt-andrej-karpathy-s-llm-in"].

- retrieved: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- reranked: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- cited: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']

## q2: What architectural change in the transformer enabled it to scale far beyond previous sequence models like RNNs and LSTMs?

**Answer:** The Transformer architecture enabled scaling beyond previous sequence models like Recurrent Neural Networks (RNNs) by replacing sequential recurrence with a parallelizable self-attention mechanism [id="yt-transformer-architecture"]. This non-sequential design allows for significant parallelization during training, which addresses the bottlenecks and slow processing inherent in RNNs [id="yt-transformer-architecture"]. RNNs were limited by compressing prior context into a single hidden state vector at each step, a limitation that the Transformer overcomes [id="yt-transformer-architecture"]. This parallelizable nature is considered the primary enabler for training models at an unprecedented scale [id="yt-transformer-architecture"].

- retrieved: ['yt-transformer-architecture']
- reranked: ['yt-transformer-architecture']
- cited: ['yt-transformer-architecture']

## q3: How does Karpathy distinguish Software 2.0 from Software 1.0, and how does the development cycle change between them?

**Answer:** Andrej Karpathy distinguishes Software 1.0 as classical programming where humans write explicit instructions using languages like Python or C++, with its program space limited by what developers can articulate [id="yt-software-1-0-vs-software"]. In contrast, Software 2.0 involves optimizing a program's skeleton, such as a neural network architecture, on large datasets, with the specific program discovered through this optimization process as learned weights [id="yt-software-1-0-vs-software"]. Software 2.0 is particularly effective for complex tasks like computer vision and speech recognition that are difficult for humans to program directly [id="yt-software-1-0-vs-software"].

The development cycle fundamentally changes between the two paradigms. In Software 1.0, the programmer writes and debugs code [id="yt-software-1-0-vs-software"]. For Software 2.0, the programmer's role shifts to that of a "teacher" or "data curator," focusing on collecting, cleaning, and meticulously labeling massive datasets [id="yt-software-1-0-vs-software"]. When a Software 2.0 system encounters an error, the solution is not to modify the code, but to augment the dataset with more labeled examples of the failure case, forming an iterative loop of data curation and model retraining [id="yt-software-1-0-vs-software"].

- retrieved: ['yt-software-1-0-vs-software']
- reranked: ['yt-software-1-0-vs-software']
- cited: ['yt-software-1-0-vs-software']

## q4: What is Yann LeCun's main critique of auto-regressive large language models, and what alternative architecture does he propose?

**Answer:** Yann LeCun's main critique of auto-regressive large language models (LLMs) is that they are fundamentally limited in achieving human-level intelligence due to their architectural focus on next-token prediction [id="yt-lecun-s-vision-human-lev"]. He asserts that these models are architecturally incapable of true reasoning, planning, or developing an internal world model, as they are limited to reactive "System 1" thinking [id="yt-lecun-s-vision-human-lev"]. This limitation leads to issues like hallucinations and unreliable multi-step reasoning, which he believes cannot be solved by simply scaling the models [id="yt-lecun-s-vision-human-lev"]. Additionally, a finite amount of high-quality training text creates a data bottleneck, further limiting their scaling potential [id="yt-lecun-s-vision-human-lev"].

As an alternative, LeCun proposes a modular "Objective-Driven AI" architecture, which is designed for reasoning, planning, and building internal world models [id="yt-lecun-s-vision-human-lev"]. This architecture is based on Joint Embedding Predictive Architectures (JEPA) for its World Model, which learns to predict abstract representations of future states from current states and actions [id="yt-lecun-s-vision-human-lev"]. The Objective-Driven AI system also includes a Perception Module for sensory input, a non-trainable Cost Module to evaluate "discomfort," and an Actor Module with an Optimizer/Planner that uses the World Model to minimize the Cost Module's output [id="yt-lecun-s-vision-human-lev"].

- retrieved: ['yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-dan-shapiro-overcoming-t']
- reranked: ['yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-dan-shapiro-overcoming-t']
- cited: ['yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-dan-shapiro-overcoming-t']

## q5: Why does the popular perception of programming get it wrong, and what skill is most important in the actual programming workflow?

**Answer:** The common perception of programming as rapid, flawless typing is inaccurate [id="yt-programming-workflow-is"]. The actual process is an iterative cycle centered on debugging, where a significant portion of time is spent diagnosing and fixing errors using external resources, rather than writing new code [id="yt-programming-workflow-is"]. The core programming skill is not typing speed, but a methodical problem-solving approach that relies heavily on searching for and applying existing solutions [id="yt-programming-workflow-is"].

- retrieved: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
- reranked: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
- cited: ['yt-programming-workflow-is', 'yt-software-1-0-vs-software']
