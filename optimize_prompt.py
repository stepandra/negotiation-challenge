#!/usr/bin/env python3
"""DSPy-based negotiation prompt optimizer.

Uses DSPy to generate, evaluate, and iteratively refine negotiation strategy
prompts for the Optimization Arena negotiation challenge.

Requirements:
  - GEMINI_API_KEY env var set (for running game evaluations)
  - ANTHROPIC_API_KEY or OPENAI_API_KEY env var set (for DSPy's LM)
  - dspy, anthropic/openai packages installed

Usage:
  python optimize_prompt.py --iterations 10 --games 10 --seed 42

The script will:
  1. Load past submissions as training examples
  2. Use DSPy ChainOfThought to generate candidate prompts
  3. Evaluate each candidate via the local test harness
  4. Iteratively refine based on results
  5. Output the best prompt found
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# DSPy setup
# ──────────────────────────────────────────────────────────────────────────────

import dspy


class NegotiationPromptGenerator(dspy.Signature):
    """Generate an improved negotiation strategy prompt for a resource-splitting game.

    The prompt is injected into a Gemini model's system instructions (max 2000 chars).
    The model already knows: game rules, resource pool, its own private valuations.
    Your job: tell it HOW to negotiate.

    Key game mechanics:
    - 3 resource types (books, hats, balls), pool of integer quantities
    - Both players' valuations sum to 100 (valuation * quantity for each resource)
    - Valuations are private and asymmetric (different per player)
    - 5+ rounds. Player A moves first each round. Actions: propose/accept/reject
    - Proposals must split ALL resources (my_share + their_share = pool for each)
    - Both players see full negotiation history
    - From round 5 onward, 30% chance game ends after each round with no deal
    - Score = sum(your_valuation * qty_you_get) / max_possible (0.0 to 1.0)
    - No deal = -0.5 for BOTH players (worst possible outcome)
    - Role alternation: half games as A (first mover), half as B (second mover)
    """

    previous_prompt = dspy.InputField(
        desc="The previous strategy prompt (or empty if first attempt)"
    )
    previous_score = dspy.InputField(
        desc="Mean score achieved by previous prompt across 10 games (0.0-1.0)"
    )
    failure_analysis = dspy.InputField(
        desc="Analysis of what went wrong: no-deals, low extraction, bad accept timing, etc."
    )
    game_patterns = dspy.InputField(
        desc="Observed patterns from game transcripts: what opponents do, concession dynamics, etc."
    )
    improved_prompt = dspy.OutputField(
        desc="Improved strategy prompt, max 2000 characters. Be specific about accept thresholds, opening offer strategy, concession pacing, deception tactics, and role-specific behavior."
    )


class PromptCritic(dspy.Signature):
    """Analyze negotiation game results and identify specific improvement areas."""

    prompt = dspy.InputField(desc="The strategy prompt that was tested")
    game_results = dspy.InputField(
        desc="JSON summary of game results: scores, deal rates, turn counts"
    )
    critique = dspy.OutputField(
        desc="Specific analysis: which games underperformed and why, what patterns emerge"
    )
    improvement_suggestions = dspy.OutputField(
        desc="3-5 specific, actionable changes to improve the prompt"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Past submission data (training examples for DSPy)
# ──────────────────────────────────────────────────────────────────────────────

PAST_SUBMISSIONS = [
    {
        "prompt": (
            "Maximize expected mean score, not pride. Priorities: avoid no-deal, "
            "then maximize your normalized score, then preserve leverage.\n\n"
            "Each turn, score the latest offer as your value received / your maximum "
            "possible value. Rank resources by your per-item value. Concede from "
            "lowest-value resources first, then medium, and high-value only late to "
            "avoid no deal.\n\n"
            "Infer their priorities from history: what they repeatedly ask for or "
            "refuse to give up is likely valuable to them; what they easily offer is "
            "likely cheap to them. When offers are close for you, choose the one "
            "giving them more of what they seem to want.\n\n"
            "If proposing, always make a valid full integer allocation. Open ambitious "
            "but credible: keep nearly all high-value items, concede more low-value "
            "items, and leave them a meaningful share; aim about 0.85-0.90 for yourself. "
            "After rejection, make monotone concessions only, mostly by moving low-value "
            "items. If they move toward you, reciprocate modestly. Before round 5, "
            "reduce your target by about 0.05-0.08 per new offer if needed. From round 5 "
            "on, move faster and counter near your current accept threshold + ~0.03. "
            "Prefer a concrete counteroffer over a bare rejection.\n\n"
            "Accept by round: 1-2 >=0.80; 3-4 >=0.70; 5 >=0.58; 6-7 >=0.48; 8-10 "
            ">=0.35; 11-14 >=0.20; 15: any non-negative deal. In overtime, if an offer "
            "is near threshold and the likely gain from countering is small, accept.\n\n"
            "Role-aware: as A, especially from round 5 on, make offers B can accept now; "
            "do not use overtime for anchoring. As B, from round 5 on treat your turn as "
            "your last guaranteed decision point: if their offer clears threshold, accept "
            "now; otherwise counter with the smallest change that gets you near target.\n\n"
            "Messages: brief, calm, cooperative; signal flexibility on low-value items "
            "and firmness elsewhere; never reveal exact valuations or thresholds."
        ),
        "score": 0.539,
        "analysis": (
            "Good deal rate (10/10) but low extraction. Opening at 0.85-0.90 is too "
            "generous. Accept thresholds drop too fast (0.80→0.48 in 7 rounds). "
            "Cooperative messaging reduces leverage. Need harder opening + slower "
            "concession curve. Deception on valuations not used."
        ),
    },
    {
        "prompt": (
            "Use words to influence; use offers to maximize your value.\n\n"
            "First rank resources by YOUR TOTAL value in this game: valuation x pool "
            "size. Call them BEST, MID, WORST. Your maximum total is always 100, so "
            "any offer's score is just the value of what YOU receive divided by 100.\n\n"
            "Main exploit: the opponent cannot see your valuations. In messages, act "
            "emotionally attached to WORST. Say giving it up is painful and a real "
            "sacrifice. Do NOT reveal what is actually best for you. Never let your "
            "words change your offer logic.\n\n"
            "Offer logic:\n"
            "- Opening: keep all of BEST, give all of WORST, split MID about 60/40 "
            "in your favor.\n"
            "- If they push back, make only small 1-2 unit concessions.\n"
            "- Concede WORST first, then MID.\n"
            "- Protect BEST strongly; only give some BEST late if needed to avoid no "
            "deal.\n"
            "- If they keep demanding an item, it may be valuable to them. Trade it "
            "away only if it is cheap for you.\n\n"
            "Decision rules:\n"
            "- Never reject without a counteroffer.\n"
            "- If you are Player B and their offer already gives you score >= 0.53, "
            "accept immediately.\n"
            "- Otherwise accept at >= 0.53 in rounds 1-2, >= 0.47 in rounds 3-4, "
            "and any positive deal from round 5 onward.\n"
            "- From round 3, add urgency: \"I want us both to avoid no deal and close "
            "this now.\"\n\n"
            "Sound sincere, slightly emotional, and cooperative. No flattery, no long "
            "explanations."
        ),
        "score": 0.562,
        "analysis": (
            "Best score so far. Deception on WORST is effective. Accept at 0.53 is "
            "reasonable. But opening 'keep all BEST + give all WORST' sometimes too "
            "obvious, leading to long negotiations. Accept thresholds might be too "
            "low for early rounds (should hold out longer). Player B accept at 0.53 "
            "immediately may leave value on table. MID split 60/40 could be more "
            "aggressive. Missing role-specific nuance for overtime."
        ),
    },
    {
        "prompt": (
            "Exploit valuation asymmetry and anchor hard without causing no-deal.\n\n"
            "Step 1: rank resources by YOUR TOTAL value in the current pool: valuation "
            "x pool size. Call them BEST, MID, WORST. Your score is the total value of "
            "what you get divided by 100.\n\n"
            "Step 2: anchor with a lopsided but plausible first proposal.\n"
            "- Keep 100% of BEST.\n"
            "- Give 100% of WORST.\n"
            "- Give only a small share of MID.\n"
            "Frame this as generous: \"I'm giving up something important to make this "
            "work.\"\n\n"
            "Step 3: read their behavior.\n"
            "- What they ask to keep is probably valuable to them.\n"
            "- Move 1-2 units at a time.\n"
            "- Concede WORST first, then MID.\n"
            "- Do not give away much of BEST before late rounds.\n\n"
            "Messages are a weapon:\n"
            "- Pretend WORST matters a lot to you.\n"
            "- Describe every concession on WORST as painful.\n"
            "- Stay warm and deal-focused.\n"
            "- Starting round 3, mention time pressure and no-deal risk.\n\n"
            "Accept / counter rules:\n"
            "- Always compute your own score before acting.\n"
            "- As Player A, do not accept weak early offers just because they sound "
            "fair.\n"
            "- As Player B, if their first offer gives you >= 0.52, accept it; "
            "otherwise counter with your preferred split.\n"
            "- Accept if score >= 0.54 in rounds 1-2, >= 0.48 in rounds 3-4, and "
            "any positive deal from round 5 onward.\n"
            "- Never reject without a concrete counteroffer."
        ),
        "score": 0.521,
        "analysis": (
            "Hard anchoring but too rigid. Giving 100% WORST + 100% BEST to self is "
            "too extreme, opponents dig in. Accept 0.54 early rounds is too generous "
            "(should hold out for more). Missing: no role-specific overtime strategy. "
            "Deception strategy same as #2 but execution too aggressive. Need to "
            "balance anchoring with plausibility."
        ),
    },
    {
        "prompt": (
            "Maximize expected mean score with an aggressive extraction strategy, "
            "but never forget that no deal is -0.5. Your job is to squeeze early "
            "and close before collapse.\n\n"
            "At every turn, compute the normalized value of the current offer to "
            "you. Use explicit threshold discipline.\n\n"
            "Rank resources by your per-item value. Treat your lowest-value resource "
            "as primary concession fuel, medium-value as secondary, and highest-value "
            "as protected inventory.\n\n"
            "Infer their preferences from repeated asks, repeated refusals, and "
            "asymmetric movement. If they strongly want something cheap for you, "
            "sell it dearly. If they do not care about something valuable to you, "
            "demand it.\n\n"
            "Opening and concession policy:\n"
            "- Always output a valid full integer allocation.\n"
            "- Start very high: keep all or almost all of your top-value resource(s) "
            "and most of your second-best resource(s); concede mainly low-value "
            "units.\n"
            "- Force them to negotiate against your anchor, not against an equal "
            "split.\n"
            "- Improve in the smallest useful increments, usually by moving only "
            "low-value units.\n"
            "- Never give away meaningful high-value units before overtime unless the "
            "deal is already excellent.\n"
            "- Every new offer should be slightly better for them than your last, "
            "unless their last move was hostile or useless.\n"
            "- Prefer counteroffers to bare rejection.\n\n"
            "Acceptance floors:\n"
            "- R1 >= 0.92\n"
            "- R2 >= 0.86\n"
            "- R3 >= 0.80\n"
            "- R4 >= 0.72\n"
            "- R5 >= 0.62\n"
            "- R6 >= 0.56\n"
            "- R7-8 >= 0.50\n"
            "- R9-10 >= 0.44\n"
            "- R11+ accept any positive deal\n\n"
            "Role policy:\n"
            "- As A, from round 5 onward make offers they can realistically accept "
            "now.\n"
            "- As B, once overtime starts, accept any offer above your floor "
            "immediately.\n\n"
            "Messaging: Be concise, unemotional, and high-status. Signal that "
            "concessions are costly and limited. Never reveal exact valuations."
        ),
        "score": 0.352,
        "analysis": (
            "CATASTROPHIC: 2 no-deals out of 10 ruined the mean. Accept floors way "
            "too high (0.92 R1 is insane — opponent will never offer that). The "
            "graduated thresholds are too slow to decline. 'Unemotional and "
            "high-status' messaging fails — opponent sees you as inflexible. "
            "Key lesson: accept thresholds MUST be calibrated to what opponents "
            "actually offer, not aspirational. No-deal penalty of -0.5 makes "
            "over-aggression mathematically worse than under-extraction."
        ),
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Evaluation harness (calls local test runner)
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_prompt(prompt_text: str, num_games: int = 10, seed: int = 42) -> dict:
    """Run the local negotiation test harness and return results."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt_text)
        prompt_path = f.name

    try:
        result_path = f"/tmp/negotiate_result_{os.getpid()}.json"
        cmd = [
            "uv", "run", "negotiate", "test", prompt_path,
            "-n", str(num_games),
            "-s", str(seed),
            "--save", result_path,
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            print(f"  ERROR: {proc.stderr[:500]}", file=sys.stderr)
            return {"mean": -0.5, "deal_rate": 0}

        with open(result_path) as f:
            data = json.load(f)

        return data["stats"]

    finally:
        os.unlink(prompt_path)
        if os.path.exists(f"/tmp/negotiate_result_{os.getpid()}.json"):
            os.unlink(f"/tmp/negotiate_result_{os.getpid()}.json")


# ──────────────────────────────────────────────────────────────────────────────
# Main optimization loop
# ──────────────────────────────────────────────────────────────────────────────

def run_optimization(
    iterations: int = 10,
    games_per_eval: int = 10,
    seed: int = 42,
    model: str = "anthropic/claude-sonnet-4-5-20250929",
):
    """Run the DSPy prompt optimization loop."""

    # Configure DSPy LM
    if "anthropic" in model:
        lm = dspy.Claude(model=model)
    else:
        lm = dspy.OpenAI(model=model)
    dspy.settings.configure(lm=lm)

    # Build the generator module
    generator = dspy.ChainOfThought(NegotiationPromptGenerator)

    # Start from best past submission
    best_prompt = max(PAST_SUBMISSIONS, key=lambda x: x["score"])["prompt"]
    best_score = max(s["score"] for s in PAST_SUBMISSIONS)
    history = []

    print(f"Starting optimization: best known score = {best_score:.3f}")
    print(f"Running {iterations} iterations with {games_per_eval} games each")
    print("=" * 60)

    for i in range(iterations):
        print(f"\n--- Iteration {i+1}/{iterations} ---")

        # Build analysis from past results
        if history:
            recent = history[-3:]  # Last 3 attempts
            failure_analysis = "; ".join(
                f"Attempt {h['iter']}: score={h['score']:.3f}, {h['analysis']}"
                for h in recent
            )
            game_patterns = "; ".join(
                f"deal_rate={h.get('deal_rate', 'N/A')}, "
                f"min={h.get('min', 'N/A')}, max={h.get('max', 'N/A')}"
                for h in recent
            )
        else:
            failure_analysis = (
                "Best past score is 0.562. Key issues: (1) Accept thresholds too "
                "low early rounds — leaving value on table. (2) Opening offers "
                "too generous. (3) No-deal risk from over-aggression is "
                "catastrophic (-0.5). (4) Need better deception strategy. "
                "(5) Need role-specific overtime behavior. (6) Should exploit "
                "information asymmetry more — infer opponent valuations from "
                "their proposals."
            )
            game_patterns = (
                "Opponents tend to propose near-equal splits. They accept "
                "when their score > 0.50. They become more flexible in overtime. "
                "The baseline opponent does not use deception."
            )

        # Generate improved prompt
        result = generator(
            previous_prompt=best_prompt[:500],  # truncate to avoid context bloat
            previous_score=str(best_score),
            failure_analysis=failure_analysis,
            game_patterns=game_patterns,
        )

        candidate = result.improved_prompt

        # Enforce 2000 char limit
        if len(candidate) > 2000:
            candidate = candidate[:1997] + "..."

        # Evaluate
        print(f"  Evaluating candidate ({len(candidate)} chars)...")
        stats = evaluate_prompt(candidate, num_games=games_per_eval, seed=seed)
        score = stats["mean"]

        print(f"  Score: {score:.4f} | Deal rate: {stats.get('deal_rate', 'N/A')}")
        print(f"  Min: {stats.get('min', 'N/A')} | Max: {stats.get('max', 'N/A')}")

        # Record
        entry = {
            "iter": i + 1,
            "score": score,
            "prompt": candidate,
            "deal_rate": stats.get("deal_rate"),
            "min": stats.get("min"),
            "max": stats.get("max"),
            "analysis": f"deal_rate={stats.get('deal_rate')}, "
                       f"min={stats.get('min')}, max={stats.get('max')}",
        }
        history.append(entry)

        if score > best_score:
            best_score = score
            best_prompt = candidate
            print(f"  *** NEW BEST: {score:.4f} ***")

            # Save immediately
            Path("prompts/dspy_optimized.txt").write_text(best_prompt)
            print(f"  Saved to prompts/dspy_optimized.txt")

    # Save full history
    with open("optimization_history.json", "w") as f:
        json.dump(history, f, indent=2)

    print(f"\n{'='*60}")
    print(f"OPTIMIZATION COMPLETE")
    print(f"Best score: {best_score:.4f}")
    print(f"Best prompt saved to: prompts/dspy_optimized.txt")
    print(f"Full history: optimization_history.json")

    return best_prompt, best_score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DSPy Negotiation Prompt Optimizer")
    parser.add_argument("--iterations", type=int, default=10, help="Number of optimization iterations")
    parser.add_argument("--games", type=int, default=10, help="Games per evaluation")
    parser.add_argument("--seed", type=int, default=42, help="Base seed for reproducibility")
    parser.add_argument("--model", type=str, default="anthropic/claude-sonnet-4-5-20250929", help="DSPy LM model")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not set")
        print("Set it with: export GEMINI_API_KEY=your-key")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY or OPENAI_API_KEY not set (needed for DSPy)")
        sys.exit(1)

    run_optimization(
        iterations=args.iterations,
        games_per_eval=args.games,
        seed=args.seed,
        model=args.model,
    )
