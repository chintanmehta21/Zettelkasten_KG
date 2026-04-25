# iter-06 QA Pairs (Browser, Live Production)

Each block: question, full answer streamed via `/api/rag/sessions/<id>/messages` (stream:true), citations with rerank scores.

---

## q1 — Karpathy LLM development stages

**Question:** According to Andrej Karpathy, what are the two main stages in the development of a large language model, and what does each stage accomplish?

**Citations (top-5):**
| node_id | rerank_score |
|---|---|
| yt-andrej-karpathy-s-llm-in ✓ gold | 0.998 |
| yt-software-1-0-vs-software | 0.745 |
| yt-lecun-s-vision-human-lev | 0.044 |
| yt-transformer-architecture | 0.001 |
| yt-programming-workflow-is | 0.00004 |

**Answer (1192 chars):**

> According to Andrej Karpathy, the development of a large language model involves a two-stage process: pre-training and fine-tuning [id="yt-andrej-karpathy-s-llm-in"].
>
> 1. **Pre-training** creates the "kernel" or base model [id="yt-andrej-karpathy-s-llm-in"]. The objective is to learn a comprehensive model of text by predicting the next token across a massive dataset [id="yt-andrej-karpathy-s-llm-in"]. This computationally intensive process ingrains grammar, facts, and reasoning abilities, resulting in a "document completer" model that can continue text statistically but does not inherently follow instructions [id="yt-andrej-karpathy-s-llm-in"].
>
> 2. **Fine-tuning** creates an assistant model by aligning the base model with human intent to be helpful and harmless [id="yt-andrej-karpathy-s-llm-in"]. This stage uses a smaller, high-quality dataset of prompt-response pairs for Supervised Fine-Tuning (SFT) and may also involve techniques like Reinforcement Learning from Human Feedback (RLHF) ...

---

## q2 — Transformer architectural change

**Question:** What architectural change in the transformer enabled it to scale far beyond previous sequence models like RNNs and LSTMs?

**Citations (top-5):**
| node_id | rerank_score |
|---|---|
| yt-transformer-architecture ✓ gold | 0.987 |
| **web-attention-mechanism-in-m** ← NEW | **0.428** |
| yt-andrej-karpathy-s-llm-in | 0.012 |
| yt-lecun-s-vision-human-lev | 0.0004 |
| yt-software-1-0-vs-software | 0.00002 |

**KG↔RAG note:** the brand-new Wikipedia Zettel correctly ranked #2 — the attention mechanism IS the architectural change in question. Cross-pollination working.

**Answer (665 chars):** woven from both top-2 Zettels — covers self-attention replacing recurrence, parallelizable training, scaling implications.

---

## q3 — Software 2.0 vs Software 1.0

**Question:** How does Software 2.0 differ from Software 1.0?

**Citations (top-6):**
| node_id | rerank_score |
|---|---|
| yt-software-1-0-vs-software ✓ gold | 0.999 |
| yt-andrej-karpathy-s-llm-in | 0.002 |
| yt-lecun-s-vision-human-lev | 0.00008 |
| yt-programming-workflow-is | 0.00007 |
| yt-transformer-architecture | 0.00007 |
| web-attention-mechanism-in-m | 0.00005 |

**Distractor performance:** all non-gold candidates at ≤0.002 rerank score. Excellent precision.

**Answer:**

> Software 1.0 is classical programming where humans write explicit instructions in languages like Python or C++ [id="yt-software-1-0-vs-software"]. In contrast, Software 2.0 is a data-driven approach where a program's skeleton, such as a neural network, is optimized on large datasets [id="yt-software-1-0-vs-software"]. The specific program in Software 2.0 is discovered through this optimization and manifests as the network's learned weights [id="yt-software-1-0-vs-software"].
>
> This leads to several key differences:
> * **Developer Role:** The programmer's role shifts from writing and debugging code to being a "teacher" or "data curator" whose main tasks are collecting, cleaning, and labeling massive datasets [id="yt-software-1-0-vs-software"].
> * **Debugging:** When a Software 2.0 system makes an error, the solution is not to modify the code but to augment the dataset with more labeled examples of the failure case and retrain the model [id="yt-software-1-0-vs-software"].
> * **Technology stack...**

---

## q4 — LeCun's JEPA critique

**Question:** What is Yann LeCun's main critique of auto-regressive large language models, and what alternative architecture does he propose?

**Result:** Server returned empty stream on 3 attempts. Live droplet hit Gemini free-tier quota; billing-key escalation (iter-06 spec/CLI feature) is not yet deployed. Retry after quota reset.

---

## q5 — Programming workflow

**Question:** Why does the popular perception of programming get it wrong, and what skill is most important in the actual programming workflow?

**Result:** Same as q4 — server-side empty stream after quota exhaustion.

---

## q6_new — Attention mechanism (NEW ZETTEL TARGET)

**Question:** How does the attention mechanism work in machine learning, and what makes it superior to recurrence-based approaches like RNNs?

**Citations (top-5):**
| node_id | rerank_score |
|---|---|
| **web-attention-mechanism-in-m** ✓ gold (NEW, ingested 5 min ago) | **0.996** |
| yt-transformer-architecture | 0.773 |
| yt-lecun-s-vision-human-lev | 0.001 |
| yt-software-1-0-vs-software | 0.0008 |
| yt-andrej-karpathy-s-llm-in | 0.0001 |

**Answer (1668 chars):**

> The attention mechanism in machine learning works by assigning "soft" weights to different components in a sequence to determine their relative importance [id="web-attention-mechanism-in-m"]. For each token, three vectors are generated: a Query (Q), a Key (K), and a Value (V) [id="yt-transformer-architecture"]. The Query vector represents what a token is looking for, while the Key vector signifies what information it offers [id="yt-transformer-architecture"]. Attention scores are calculated by taking the dot product of a token's Query vector with every other token's Key vector [id="yt-transformer-architecture"]. These scores are then converted into weights that sum to one, and the final output for the token is a weighted sum of all the Value vectors in the sequence [id="yt-transformer-architecture"].
>
> This approach is superior to recurrence-based models like Recurrent Neural Networks (RNNs) because it overcomes their primary limitations [id="web-attention-mechanism-in-m"]. RNNs process...

**Why this matters:** the NEW Zettel was retrieved and cited as the primary source for a question targeting its content, AND the mechanically-related transformer Zettel was correctly ranked #2 to fuse the conceptual ("soft weights", "Q/K/V") with the architectural ("self-attention replaces recurrence") perspectives. End-to-end KG↔RAG cohesion validated on a 5-minute-old Zettel.
