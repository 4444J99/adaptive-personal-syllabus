# Adaptive Personal Syllabus

[![CI](https://github.com/4444J99/adaptive-personal-syllabus/actions/workflows/ci.yml/badge.svg)](https://github.com/4444J99/adaptive-personal-syllabus/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-pending-lightgrey)](https://github.com/4444J99/adaptive-personal-syllabus)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/4444J99/adaptive-personal-syllabus/blob/main/LICENSE)
[![Organ VI](https://img.shields.io/badge/Organ-VI%20Koinonia-6366F1)](https://github.com/organvm-vi-koinonia)
[![Status](https://img.shields.io/badge/status-active-brightgreen)](https://github.com/4444J99/adaptive-personal-syllabus)
[![Python](https://img.shields.io/badge/lang-Python-informational)](https://github.com/4444J99/adaptive-personal-syllabus)

**An AI-personalized education system that transforms generic curricula into context-aware, multi-artifact learning journeys spanning OS development, algorithms, DSLs, kernel engineering, UI/sound/video, and AR/VR -- generating eight parallel professional outputs per module through a "Wings" multi-artifact framework.**

---

## Table of Contents

1. [Educational Philosophy](#1-educational-philosophy)
2. [Curriculum Overview](#2-curriculum-overview)
3. [Technical Architecture](#3-technical-architecture)
4. [Installation and Setup](#4-installation-and-setup)
5. [Usage](#5-usage)
6. [Working Examples](#6-working-examples)
7. [Pedagogical Foundation](#7-pedagogical-foundation)
8. [Testing and Quality](#8-testing-and-quality)
9. [Cross-References](#9-cross-references)
10. [Contributing](#10-contributing)
11. [License and Author](#11-license-and-author)

---

## 1. Educational Philosophy

Most educational content is written for nobody in particular. Self-help books, online courses, and university syllabi present general principles under the assumption that the reader will perform the translation work themselves -- mapping abstract advice onto the concrete circumstances of their own life, career, and projects. The Adaptive Personal Syllabus rejects this assumption. Its central claim is that AI can close the personalization gap: every piece of educational content should be processed through personalization protocols that rewrite it for YOUR business, YOUR metrics, YOUR context, YOUR life.

Consider a canonical example. *Think and Grow Rich* contains 13 principles for wealth accumulation. For a reader who is a solo software engineer building a SaaS product, those principles mean something radically different than they do for a reader who is a visual artist pursuing grant funding. The Adaptive Personal Syllabus does not leave this translation to the reader. Instead, the system ingests the source material, cross-references it with the learner's declared goals, current skill levels, professional context, and personal metrics, and generates a rewritten version where every principle, exercise, and recommendation has been adapted to the learner's specific situation.

This philosophy extends beyond books. The entire curriculum -- spanning nine modules from foundational tooling through AR/VR neural-symbolic systems -- is designed to be personalized at the point of delivery. The system maintains a learner profile that evolves as modules are completed, ensuring that later modules build on the demonstrated competencies and identified gaps from earlier ones. The result is not a static syllabus but a living document that adapts its depth, pacing, and emphasis to the individual.

### The Wings Framework

Personalization is only half the design. The other half is the recognition that learning produces professional artifacts, not just knowledge. Every module in the Adaptive Personal Syllabus generates eight parallel outputs through the Wings framework:

| Wing | Artifact Type | Purpose |
|------|--------------|---------|
| Academic | Research paper or formal summary | Demonstrates scholarly engagement with the material |
| SOP | Standard operating procedure | Translates knowledge into repeatable institutional process |
| Business | Pitch deck or business case | Frames the module's content as commercial value proposition |
| Social | Social media post or thread | Distills insights for public-facing distribution |
| Community | Discussion prompt or forum post | Seeds collaborative engagement around the module's themes |
| Wiki | Encyclopedia-style entry | Creates reference documentation for knowledge bases |
| Web/Blog | Long-form blog post | Publishes the learning journey as narrative content |
| Grants | Grant proposal section | Positions the module's output as fundable work |

This eight-wing structure means that completing a single module on, say, kernel subsystems and observability simultaneously produces a research summary suitable for a conference submission, an SOP for the learner's engineering team, a blog post for their public portfolio, and a grant proposal section for their next funding application. The Wings framework treats education not as consumption but as production -- every hour of learning generates reusable professional capital.

---

## 2. Curriculum Overview

The curriculum is structured as nine modules plus a capstone, progressing from foundational tooling through increasingly sophisticated systems engineering. Each module builds on the previous one, and each generates a full set of Wings artifacts.

### Module Progression

| Module | Title | Focus | Key Deliverables |
|--------|-------|-------|-----------------|
| 0 | ChainBlockARK & Foundational Wings | Self-documenting ledger of prompts, commits, builds, and AI interactions | Provenance chain, initial Wings templates |
| 1 | Repo & AI Workflow Setup | Git, metadata conventions, VS Code + Copilot configuration | Configured development environment, CI/CD scaffolding |
| 2 | Algorithms & Recursive Intuition | Recursion, data structures, visual explainers | Algorithm visualizations, complexity analysis documents |
| 3 | DSL & Meta-Circular Interpreter | Lisp-style interpreter, tiny DSL for OS configuration | Working interpreter, DSL specification document |
| 4 | Bootloader & Core Kernel Loop | 16KB assembly bootloader, QEMU-tested minimal kernel | Bootable kernel image, hardware abstraction layer |
| 5 | Kernel Subsystems & Observability | Memory management, filesystem, I/O drivers, eBPF tracing | Observable kernel with tracing infrastructure |
| 6 | UI, Sound & Video Ecosystem | 2D web terminal with audio, React Native mobile demo | Multi-modal interface prototype |
| 7 | AR/VR & Neural-Symbolic Extension | AR overlay, VR scene, SMT checks, AI code generation | Spatial computing prototype, formal verification proofs |
| Capstone | Unified Microkernel + Multi-Modal Platform | Integration of all modules into a single coherent system | End-to-end platform demonstration |

### Progressive Complexity

The modules are ordered by dependency and conceptual difficulty. Modules 0-1 establish the learner's working environment and provenance infrastructure. Modules 2-3 build computational thinking skills (recursion, data structures, language design) that are prerequisites for the systems work in Modules 4-5. Modules 6-7 extend the kernel foundation into user-facing domains (interfaces, spatial computing, formal methods). The capstone integrates all prior work into a unified microkernel with multi-modal capabilities.

This progression is deliberate. A learner who completes Module 4 (bootloader and kernel) has already internalized recursive thinking (Module 2) and language design (Module 3), which means they approach kernel code not as rote implementation but as an exercise in designing layered abstractions. The curriculum teaches systems thinking through systems building.

---

## 3. Technical Architecture

### Module Structure

Each module is organized as a self-contained directory with a consistent internal layout:

```
modules/
  module-00-chainblockark/
    README.md                  # Module overview, objectives, prerequisites
    syllabus.yaml              # Machine-readable module specification
    personalization/
      profile-schema.json      # Learner profile fields relevant to this module
      adaptation-rules.py      # Context-aware rewriting logic
    wings/
      academic.md.j2           # Jinja2 template for Academic wing
      sop.md.j2                # Jinja2 template for SOP wing
      business.md.j2           # Jinja2 template for Business wing
      social.md.j2             # Jinja2 template for Social wing
      community.md.j2          # Jinja2 template for Community wing
      wiki.md.j2               # Jinja2 template for Wiki wing
      web-blog.md.j2           # Jinja2 template for Web/Blog wing
      grants.md.j2             # Jinja2 template for Grants wing
    exercises/
      ...                      # Hands-on tasks, starter code, test harnesses
    readings/
      reading-list.yaml        # Curated sources with annotations
    tie-ins/
      arts-humanities.md       # Cross-disciplinary connections
      math-sciences.md
      philosophy.md
  module-01-repo-ai-workflow/
    ...
```

### Wings Generation Pipeline

The Wings pipeline transforms raw module content into eight personalized artifacts. The process has four stages:

1. **Profile Loading** -- The learner's profile (goals, skill levels, professional context, metrics) is loaded from `~/.adaptive-syllabus/profile.yaml`. This profile is updated after each module completion based on demonstrated competencies and self-assessment.

2. **Content Ingestion** -- The module's `syllabus.yaml`, exercise results, and reading annotations are parsed into a structured content graph. External sources (books, papers, courses) referenced in the module are processed through personalization protocols.

3. **Template Rendering** -- Each wing's Jinja2 template is rendered with the combined context of the learner profile and the content graph. The adaptation rules in `adaptation-rules.py` control how generic content is rewritten for the learner's specific situation.

4. **Output Assembly** -- Rendered artifacts are written to `output/<module>/<wing>/` with metadata headers that track provenance (which sources were used, which profile fields influenced the adaptation, timestamps).

```
profile.yaml ──┐
                ├──→ [Adaptation Engine] ──→ 8 Wing Artifacts
syllabus.yaml ─┘         │
                    adaptation-rules.py
```

### Personalization Engine

The personalization engine is the core innovation. It operates on a simple principle: every statement in the source material that references a generic subject ("your business," "your team," "the reader") is rewritten to reference the learner's specific context. This is not summarization or paraphrasing -- it is contextual rewriting that preserves the source material's reasoning while grounding it in the learner's reality.

The engine uses a combination of template-based rewriting (for structural elements like exercises and checklists) and LLM-assisted rewriting (for narrative content like explanations and case studies). The learner profile provides the grounding context, and the adaptation rules define which profile fields are relevant to each content type.

---

## 4. Installation and Setup

### Prerequisites

- Python 3.11 or later
- Git 2.40+
- An OpenAI-compatible API key (for LLM-assisted personalization)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/4444J99/adaptive-personal-syllabus.git
cd adaptive-personal-syllabus

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Initialize a learner profile (local JSON file)
syllabus profile init --name "Jane Doe" --goals "build recursive systems" --context '{}'

# Verify installation
syllabus version
```

### Configuration

The system reads configuration from three sources, in order of precedence:

1. **CLI flags** -- Override any setting for a single invocation
2. **Environment variables** -- Prefixed with `APS_` (e.g., `APS_API_KEY`, `APS_MODEL`)
3. **Configuration file** -- `~/.adaptive-syllabus/config.yaml`

```yaml
# ~/.adaptive-syllabus/config.yaml
api:
  provider: openai          # openai | anthropic | local
  model: gpt-4o             # Model identifier
  api_key_env: APS_API_KEY  # Environment variable holding the key

output:
  directory: ./output        # Where generated Wings artifacts are written
  format: markdown           # markdown | html | pdf

personalization:
  depth: full                # full | summary | outline
  voice: professional        # professional | academic | casual
```

### Learner Profile Initialization

Use `syllabus profile init` to generate `~/.adaptive-syllabus/profile.json`:

```bash
syllabus profile init \
  --name "Jane Doe" \
  --organs I,V \
  --level beginner \
  --goals "build recursive systems,ship portfolio artifacts" \
  --context '{"industry":"developer tools","weekly_hours":10}'
```

```json
{
  "schema_version": "1.0",
  "name": "Jane Doe",
  "organs_of_interest": ["I", "V"],
  "level": "beginner",
  "goals": ["build recursive systems", "ship portfolio artifacts"],
  "context": {
    "industry": "developer tools",
    "weekly_hours": 10
  },
  "completed_modules": []
}
```

---

## 5. Usage

### Module Progression (Roadmap, Not Yet Implemented CLI)

The `aps module|wings|personalize` commands shown in this section are design targets and are not part of the current shipped CLI. Use the implemented `syllabus` command group shown in **Implemented Local-First CLI (Current)**.

Work through modules sequentially. Each module must be completed before the next one unlocks (though the system allows preview access for planning purposes):

```bash
# List all modules and your progress
aps modules list

# Start Module 0
aps module start 0

# View module objectives and reading list
aps module info 0

# Complete exercises (tracked automatically)
aps exercise submit module-00/exercise-01.py

# Generate Wings artifacts for a completed module
aps wings generate 0

# View your overall progress
aps progress
```

### Artifact Generation (Roadmap, Not Yet Implemented CLI)

The Wings generation command produces all eight artifacts for a given module:

```bash
# Generate all 8 Wings for Module 0
aps wings generate 0

# Generate a specific wing
aps wings generate 0 --wing academic

# Regenerate with updated profile
aps wings generate 0 --refresh-profile

# Export to different format
aps wings generate 0 --format pdf
```

Generated artifacts appear in the output directory:

```
output/
  module-00-chainblockark/
    academic.md
    sop.md
    business.md
    social.md
    community.md
    wiki.md
    web-blog.md
    grants.md
    metadata.json          # Provenance and generation context
```

### Content Personalization (Roadmap, Not Yet Implemented CLI)

Process external books and courses through the personalization engine:

```bash
# Personalize a book for your context
aps personalize book "Think and Grow Rich" --source-file think-grow-rich.txt

# Personalize a course syllabus
aps personalize course "MIT 6.S081" --url https://pdos.csail.mit.edu/6.S081/

# View personalization diff (original vs. adapted)
aps personalize diff output/personalized/think-grow-rich.md
```

### Implemented Local-First CLI (Current)

The currently implemented CLI command is `syllabus` (from `pyproject.toml`), with a local-first SQLite runtime at `~/.adaptive-syllabus/adaptive_syllabus.db`. A compatibility alias `aps` is also provided and points to the same CLI entrypoint.

```bash
# 1) Ingest repository corpus with deterministic deduplication
syllabus corpus ingest --root . --snapshot local-repo

# 2) Inspect stable JSON corpus stats schema
syllabus corpus stats
syllabus corpus stats --snapshot-name latest

# 3) Initialize learner profile
syllabus profile init \
  --name "Jane Doe" \
  --organs I,V \
  --level beginner \
  --goals "build recursive systems,ship portfolio artifacts" \
  --context '{"industry":"developer tools","weekly_hours":10}'

# 4) Generate plan from profile + ingested corpus evidence
syllabus plan generate --profile ~/.adaptive-syllabus/profile.json --format json

# 5) Run default no-op chamber hook (AAW extension point)
syllabus chamber run --hook input_ritual --dry-run

# 6) Verify append-only ledger integrity
syllabus ledger verify
```

Supported corpus extensions in MVP1:

`md, txt, yaml, yml, json, toml, csv, tsv, rst, pdf, docx`

---

## 6. Working Examples

### Module 0 Walkthrough: ChainBlockARK

Module 0 establishes the provenance infrastructure that tracks all subsequent learning activity. The ChainBlockARK (Chain-Block-Archive) is a self-documenting ledger that records every prompt sent to an AI, every commit made, every build executed, and every reading note taken. This is not blockchain in the cryptocurrency sense -- it is a hash-chained append-only log that makes learning activity auditable and reproducible.

**Step 1: Initialize the ledger**

```bash
aps module start 0
# Creates ~/.adaptive-syllabus/chainblockark.db (SQLite)
# Generates genesis block with learner profile hash
```

**Step 2: Complete the foundational exercises**

The exercises for Module 0 introduce hash chaining, append-only data structures, and provenance metadata:

```python
# exercise-01: Implement a minimal hash chain
from adaptive_personal_syllabus.chainblockark import Block, Chain

chain = Chain()
chain.append(Block(
    action="reading_note",
    source="SICP Chapter 1.1",
    content="Substitution model of evaluation...",
    learner_reflection="Connection to recursive-engine organ handlers"
))

assert chain.verify_integrity()
print(f"Chain length: {len(chain)} blocks")
print(f"Latest hash: {chain.head.hash[:16]}...")
```

**Step 3: Generate Wings artifacts**

After completing Module 0's exercises, generate the eight Wings:

```bash
aps wings generate 0
```

### Wings Output Samples

Below are excerpts from the Wings artifacts generated for a learner whose profile indicates they are a senior software engineer building IoT embedded systems:

**Academic Wing (excerpt):**
> This module establishes a provenance-tracking infrastructure inspired by Merkle tree structures (Merkle, 1979) and applied to educational activity logging. Unlike conventional learning management systems that track only completion status, the ChainBlockARK maintains cryptographic integrity guarantees over the full sequence of learner interactions, enabling reproducible audit trails for competency claims.

**Business Wing (excerpt):**
> For Acme Corp's IoT developer tooling platform, the ChainBlockARK pattern translates directly into a customer-facing feature: auditable firmware update chains. Each update to a deployed device can be tracked through a hash-chained ledger, providing the compliance documentation required by IEC 62443 (industrial cybersecurity) without additional third-party audit infrastructure.

---

## 7. Pedagogical Foundation

The curriculum is grounded in established educational research and systems engineering practice:

- **Constructivism** (Piaget, Vygotsky): Learners construct knowledge through active engagement with problems in their own context, not passive reception of abstract principles.
- **Deliberate Practice** (Ericsson): Modules are structured around focused exercises with clear success criteria and immediate feedback.
- **Cognitive Apprenticeship** (Collins, Brown, Newman): The system makes expert thinking visible by showing how source material is adapted, not just the final adapted result.
- **Systems Thinking** (Meadows, Senge): Later modules require integrating prior modules, teaching learners to reason about layered systems rather than isolated components.

---

## 8. Testing and Quality

The repository maintains quality gates for documentation and code:

- `pytest` for unit and integration tests of the personalization engine and CLI
- `ruff` for linting and formatting
- `mypy` for type checking
- Documentation audit scripts that verify internal links, badge freshness, and module consistency

CI runs on every push and pull request.

---

## 9. Cross-References

Related projects in the ORGAN VI community and broader organvm ecosystem:

| Project | Description | Relevance |
|---------|-------------|-----------|
| [salon-archive](https://github.com/organvm-vi-koinonia/salon-archive) | Archive infrastructure for intellectual salons: transcription pipeline, topic taxonomy, and session metadata | Salon discussions feed into curriculum refinement; Module exercises can be adapted for salon workshops |
| [reading-group-curriculum](https://github.com/organvm-vi-koinonia/reading-group-curriculum) | Structured reading group curricula spanning eight-organ domains: 8-12 week programs with curated reading lists | Reading lists inform module readings; reading group formats inform Community Wing templates |

---

## 10. Contributing

Contributions are welcome, particularly in these areas:

- **New module exercises** -- Hands-on tasks that reinforce module concepts. Include starter code and test harnesses.
- **Wings template improvements** -- Better Jinja2 templates that produce more natural and useful artifacts across the eight wing types.
- **Reading list expansions** -- Additional foundational texts with annotations explaining their relevance to specific modules.
- **Interdisciplinary tie-ins** -- New connections between technical modules and arts, humanities, sciences, or philosophy.
- **Personalization rules** -- More sophisticated adaptation logic for specific professional contexts (academia, startups, enterprise, creative practice).

### Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-exercise-module-03`)
3. Write tests for new functionality
4. Ensure all quality gates pass (`pytest`, `ruff`, `mypy`)
5. Submit a pull request with a description of what the contribution adds and which module(s) it affects

Please review the community guidelines in [organvm-vi-koinonia/.github](https://github.com/organvm-vi-koinonia/.github) before contributing.

---

## 11. License and Author

**License:** MIT

**Author:** [@4444j99](https://github.com/4444J99)

**Part of the Eight-Organ System:**

| Organ | Domain | GitHub Organization |
|-------|--------|-------------------|
| I | Theory | [organvm-i-theoria](https://github.com/organvm-i-theoria) |
| II | Art | [organvm-ii-poiesis](https://github.com/organvm-ii-poiesis) |
| III | Commerce | [organvm-iii-ergon](https://github.com/organvm-iii-ergon) |
| IV | Orchestration | [organvm-iv-taxis](https://github.com/organvm-iv-taxis) |
| V | Public Process | [organvm-v-logos](https://github.com/organvm-v-logos) |
| **VI** | **Community** | **[organvm-vi-koinonia](https://github.com/organvm-vi-koinonia)** |
| VII | Marketing | [organvm-vii-kerygma](https://github.com/organvm-vii-kerygma) |
| Meta | Governance | [meta-organvm](https://github.com/meta-organvm) |

---

*Adaptive Personal Syllabus is part of ORGAN VI (Koinonia) -- the community organ of the eight-organ creative-institutional system.*

<!-- SYSTEM-NAV-START -->

---

<sub>[Portfolio](https://4444j99.github.io/portfolio/) · [System Directory](https://4444j99.github.io/portfolio/directory/) · [ORGAN VI · Koinonia](https://organvm-vi-koinonia.github.io/) · Part of the <a href="https://4444j99.github.io/portfolio/directory/">ORGANVM eight-organ system</a></sub>

<!-- SYSTEM-NAV-END -->
