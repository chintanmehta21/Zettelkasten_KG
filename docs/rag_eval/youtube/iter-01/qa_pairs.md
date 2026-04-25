# QA pairs - iter-01

## q1: According to Andrej Karpathy, what are the two main stages in the development of a large language model, and what does each stage accomplish?

**Answer:** According to Andrej Karpathy, the development of a large language model involves a two-stage process: pre-training and fine-tuning [id="yt-andrej-karpathy-s-llm-in"].

1.  **Pre-training Base Models**: This stage is analogous to creating the "kernel" or base model of an operating system. Its objective is to learn a comprehensive model of text by predicting the next token across a massive dataset, such as Llama 2's 2 trillion tokens. This process creates a "blurry JPEG of the web," a lossy compression of its training data, which can explain model "hallucinations." The output is a "document completer" base model that statistically continues text but does not inherently follow instructions [id="yt-andrej-karpathy-s-llm-in"].
2.  **Fine-tuning Assistant Models**: This stage creates an assistant model by aligning the base model with human intent to be a helpful and harmless agent. It uses a smaller, high-quality dataset of prompt-response pairs for Supervised Fine-Tuning (SFT) and often includes Reinforcement Learning from Human Feedback (RLHF) or Constitutional AI. The output is an instruction-following assistant model, like ChatGPT, where its "personality" and helpfulness are crafted [id="yt-andrej-karpathy-s-llm-in"].

- retrieved: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software', 'yt-lecun-s-vision-human-lev']
- reranked: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software', 'yt-lecun-s-vision-human-lev']
- cited: ['yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software', 'yt-lecun-s-vision-human-lev']

## q2: What architectural change in the transformer enabled it to scale far beyond previous sequence models like RNNs and LSTMs?

**Answer:** The Transformer architecture enabled unprecedented scaling of neural networks for sequential data by replacing sequential recurrence with a parallelizable self-attention mechanism [id="yt-transformer-architecture"]. This non-sequential design allows for significant parallelization during training, addressing the bottlenecks and slow processing inherent in older models like Recurrent Neural Networks (RNNs) [id="yt-transformer-architecture"]. The parallelizable nature of the Transformer architecture is considered the primary enabler for training models at an unprecedented scale [id="yt-transformer-architecture"].

- retrieved: ['yt-transformer-architecture', 'yt-andrej-karpathy-s-llm-in', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software']
- reranked: ['yt-transformer-architecture', 'yt-andrej-karpathy-s-llm-in', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software']
- cited: ['yt-transformer-architecture', 'yt-andrej-karpathy-s-llm-in', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software']

## q3: How does Karpathy distinguish Software 2.0 from Software 1.0, and how does the development cycle change between them?

**Answer:** Andrej Karpathy distinguishes Software 1.0 as classical programming where humans write explicit instructions using languages like Python or C++. Its program space is limited by what human developers can explicitly design. Software 2.0, in contrast, is an approach where a program's skeleton, such as a neural network architecture, is optimized on large datasets, and the specific program is discovered through this optimization process as the network's learned weights [id="yt-software-1-0-vs-software"]. Software 2.0 excels at complex tasks difficult for humans to program directly, such as computer vision and speech recognition, with examples like AlphaGo demonstrating its efficacy [id="yt-software-1-0-vs-software"].

The development cycle for Software 2.0 fundamentally differs from traditional software engineering. In Software 2.0, the programmer's role shifts from writing and debugging code to that of a "teacher" or "data curator." Core tasks involve collecting, cleaning, and meticulously labeling massive datasets. If a Software 2.0 system produces an error, the solution is to augment the dataset with more labeled examples of the failure case, rather than modifying the code. This iterative loop of data curation followed by model retraining constitutes the new development cycle [id="yt-software-1-0-vs-software"].

- retrieved: ['yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-programming-workflow-is', 'yt-zero-day-market-covert-exploits', 'yt-lecun-s-vision-human-lev']
- reranked: ['yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-programming-workflow-is', 'yt-zero-day-market-covert-exploits', 'yt-lecun-s-vision-human-lev']
- cited: ['yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-programming-workflow-is', 'yt-zero-day-market-covert-exploits', 'yt-lecun-s-vision-human-lev']

## q4: What is Yann LeCun's main critique of auto-regressive large language models, and what alternative architecture does he propose?

**Answer:** Yann LeCun's main critique of auto-regressive large language models (LLMs) is that they are fundamentally limited in achieving human-level intelligence due to their architectural focus on next-token prediction [id="yt-lecun-s-vision-human-lev"]. This limitation restricts them to reactive "System 1" thinking, preventing true reasoning, planning, or the development of an internal world model [id="yt-lecun-s-vision-human-lev"]. He states that hallucinations and unreliable multi-step reasoning are direct consequences of this flaw, which cannot be resolved by scaling alone, and that a finite amount of high-quality training text creates a data bottleneck [id="yt-lecun-s-vision-human-lev"].

As an alternative, LeCun proposes an "Objective-Driven AI" architecture, which is based on Joint Embedding Predictive Architectures (JEPA) [id="yt-lecun-s-vision-human-lev"]. This modular system is designed for reasoning, planning, and building internal world models, aiming to achieve human-level intelligence [id="yt-lecun-s-vision-human-lev"]. The architecture includes a Perception Module, a World Model that simulates dynamics using a JEPA-style approach, a non-trainable Cost Module to evaluate "discomfort," and an Actor Module that proposes action sequences [id="yt-lecun-s-vision-human-lev"]. An Optimizer/Planner then evaluates these sequences using the World Model to minimize the Cost Module's output, a process analogous to "System 2" reasoning [id="yt-lecun-s-vision-human-lev"].

- retrieved: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- reranked: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']
- cited: ['yt-lecun-s-vision-human-lev', 'yt-andrej-karpathy-s-llm-in', 'yt-software-1-0-vs-software']

## q5: Why does the popular perception of programming get it wrong, and what skill is most important in the actual programming workflow?

**Answer:** The common perception of programming as rapid, flawless typing is inaccurate [id="yt-programming-workflow-is"]. The actual process is an iterative cycle focused on debugging, where a significant amount of time is spent diagnosing and fixing errors using external resources rather than writing new code [id="yt-programming-workflow-is"]. This cycle indicates that the core programming skill is not typing speed, but a methodical problem-solving approach that heavily relies on searching for and applying existing solutions [id="yt-programming-workflow-is"].

- retrieved: ['yt-programming-workflow-is', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-effective-public-speakin']
- reranked: ['yt-programming-workflow-is', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-effective-public-speakin']
- cited: ['yt-programming-workflow-is', 'yt-lecun-s-vision-human-lev', 'yt-software-1-0-vs-software', 'yt-andrej-karpathy-s-llm-in', 'yt-effective-public-speakin']
