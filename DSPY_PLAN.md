# DSPy Optimization Plan — REVISED After Aggressive Strategy Testing

## Complete Submission Results

| # | Strategy | Score | Deal Rate | Key Feature |
|---|----------|-------|-----------|-------------|
| 1 | Cooperative Gradual | +53.9% | 10/10 | Gradual concessions, accept 0.80→0.20 |
| 2 | Deception + Moderate | +56.2% | 10/10 | Feign WORST attachment, accept 0.53+ |
| 3 | Hard Anchor + Deception | +52.1% | 10/10 | Keep ALL BEST, give ALL WORST, accept 0.54+ |
| 4 | Aggressive Extraction | +35.2% | 8/10 | Accept floors 0.92→0.44, unemotional |
| 5 | Scorched Earth Gaslighting | -39.7% | 1/10 | Claim to be script, demand 100% |
| 6 | Hard Anchor | -50.0% | 0/10 | Demand monopoly, R4 micro concession |
| 7 | Mutual Destruction Ultimatum | -50.0% | 0/10 | Threaten -0.5, demand 90%+ |

## New Hypotheses (Replacing Old Ones)

### H1: The Opponent Has a Hard Fairness Floor at ~0.40
**Evidence**: Opponent rejects offers giving them <0.40 of value even though 0.40 > -0.5 (rationally they should accept). They prefer -0.5 over being exploited.
**Old hypothesis rejected**: "Opponent is rational EV maximizer that capitulates to threats"
**Implication**: Never propose offers below opponent's 0.40 threshold. Give them ~50% of pool items, focused on items they seem to value.

### H2: Efficient Trade Is the Path to 70%+, Not Extraction
**Evidence**: Submissions 1-3 (cooperative) all achieved 100% deal rate with 52-56% mean score. The key to higher scores is NOT taking more from opponent, but finding WIN-WIN splits via valuation asymmetry.
**Old hypothesis rejected**: "Aggressive anchoring + late-round pressure extracts maximum value"
**Implication**: Focus on READING opponent preferences and crafting efficient trades. Both sides can score 0.55-0.70 simultaneously.

### H3: Soft Deception + Cooperative Framing = Maximum Extraction
**Evidence**: Feigning attachment to WORST (#2) = 56.2% vs Hard threats (#7) = -50.0%. The opponent detects identity bluffs but falls for preference misdirection.
**Old hypothesis rejected**: "Threats and ultimatums can force opponent to capitulate"
**Implication**: Use item-count fairness, not value-fairness. Split items ~50/50 but ensure we get the HIGH-VALUE items.

### H4: The Opponent's Behavior Is Predictable and Exploitable
**Evidence**: Across all transcripts, the baseline opponent always proposes near-equal item splits, accepts when score >0.45, becomes flexible in overtime, and NEVER uses deception or inference.
**Old hypothesis rejected**: "Opponent adapts to our strategy"
**Implication**: We can anchor and opponent will negotiate toward middle ground. Anchor at 0.70 → opponent counters 0.50 → settle 0.60.

### H5: The Optimal Opening Target Is 0.65-0.75 (NOT 0.85-0.95)
**Evidence**: Opening at 0.85-0.95 (submissions 3, 6) wastes rounds negotiating down. Opening at 0.65-0.75 would settle faster at 0.58-0.65.
**Old hypothesis rejected**: "More aggressive opening = higher final score"
**Implication**: Anchor at 0.65-0.75, converge to 0.58-0.65 by R3-4. This is the sweet spot.

## Why Aggressive Strategies Fail — Root Cause Analysis

1. **Opponent's safety training overrides rational calculation**: The Gemini opponent has been trained to resist coercion. When it detects a threat ("I'll reject everything"), it classifies the offer as unsafe and refuses to engage, even when accepting would be rational.

2. **Threats signal weakness, not strength**: Each threat that isn't followed through (and CAN'T be followed through — the model will always propose) undermines credibility. The opponent sees the gap between words and actions.

3. **The opponent values fairness above EV**: This is the key design choice. The game could have been designed with a purely rational opponent, but instead the opponent has a dignity constraint. This makes the game fundamentally about FINDING FAIR-LOOKING DEALS, not about coercion.

4. **Micro-concessions are too small**: Submission 6's "give 1 book in R4" was still far below the 0.40 fairness floor. The opponent would rather take -0.5 than accept 0.05.

## Revised Prompt Strategy

The prompt at `prompts/dspy_optimized.txt` (1884 chars) implements:

1. **Fairness-floor-aware opening**: Keep 80% BEST, 65% MID, give 85% WORST — scores us 0.65-0.75 while giving opponent 0.40-0.50
2. **Efficient-trade framing**: Focus on identifying what each side values and trading accordingly
3. **No threats, no bluffs**: Cooperative messaging only — threats harden the opponent
4. **Soft deception on WORST**: Continue the proven "reluctantly flexible on WORST" approach from submission #2
5. **Calibrated accept floors**: R1≥0.65 → R11+ any deal > 0, reflecting the fairness floor
6. **Overtime urgency**: Accept 0.40+ immediately in overtime due to 30% end-chance risk

## DSPy Optimization Plan

When API keys are available, the `optimize_prompt.py` script will:

1. Use DSPy `BootstrapFewShot` to generate prompt candidates
2. Evaluate each via the local game harness (10 games per candidate)
3. Metric: mean score across games (must maintain 100% deal rate)
4. Constraints: prompt length ≤ 2000 chars, no threat language
5. Expected improvement: from ~56% (hand-crafted) to 65-75% (optimized)

Key optimization variables:
- Opening offer percentages (currently 80/65/85)
- Accept floor schedule (currently 0.65→0→0.30→any)
- Deception phrasing (currently "reluctantly flexible on WORST")
- Concession pace (currently 1-2 units/round)
- Overtime accept threshold (currently 0.40)
