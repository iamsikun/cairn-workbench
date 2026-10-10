# Formal theory, mathematical statistics, economic theory, and optimization

Load this guide when the contribution is a theorem, model, estimator with guarantees,
or algorithm with analytical properties.

## Contents
1. Stating the result exactly
2. Finding the assumption that does the work
3. Reading a proof
4. Reconstructing an economic or decision model
5. Statistical procedures and guarantees
6. Optimization and algorithms
7. Empirical translation
8. Common misreadings

---

## 1. Stating the result exactly

Restate the main result with everything that makes it true:

- **Quantifiers:** "for all distributions in class P" vs. "there exists", uniform vs.
  pointwise, and "with probability at least 1−δ" vs. "in expectation".
- **Regime:** fixed vs. growing dimension, n → ∞ vs. finite n, the rates at which
  nuisance quantities converge, and large-market or continuum approximations.
- **Objects:** the precise definition of the target, which may be a parameter, an
  equilibrium, a functional, or a risk. Note definitions that differ from standard usage.
- **Type of statement:** existence, uniqueness, characterization, comparative static,
  bound (upper or lower), impossibility, or equivalence.

Give the theorem number and page of the inspected version. When the intuition in the
introduction differs from the formal statement, the formal statement wins, so report
the gap.

## 2. Finding the assumption that does the work

For each important assumption, ask:

- **Role:** which step of the argument uses it.
- **Necessity:** whether a counterexample or a lower bound shows it can't be dropped, or
  whether it is only convenient.
- **Strength:** what familiar conditions it compares to. Is it weaker or stronger than in
  the closest predecessor? Weakening an assumption is often the contribution.
- **Checkability:** whether the assumption can be checked in an application, or whether
  it is a high-level condition the user must trust.

The most useful sentence in a theory reading often has the form: "The result needs X
because, without it, Y can happen. Here is a two-line example."

## 3. Reading a proof

1. Read the statement and the proof outline (when the paper gives one) before the
   details.
2. Find the **pivotal step**, the place where the new idea enters. Examples are a novel
   decomposition, a coupling, a fixed-point argument, an orthogonality condition, or a
   change of measure.
3. Classify the other steps as routine (a standard inequality, a textbook lemma) or
   non-routine. Explain non-routine steps and name routine ones.
4. Check the pivotal step in a simple special case, such as a scalar parameter, two
   types, or a linear model.
5. In a deep reading, state which steps you verified line by line and which you took on
   trust. Do not claim to have verified a proof you skimmed.
6. Check that a cited lemma's hypotheses hold where it is used, and preserve the order
   of limits, conditioning, and quantifiers. A numerical special case is a sanity check,
   not a proof; identify a suspected gap precisely and keep it distinct from a step
   you have not yet understood.

## 4. Reconstructing an economic or decision model

- **Environment:** agents, actions, timing, information (who knows what, and when),
  payoffs, and constraints.
- **Solution concept:** Nash, subgame-perfect, Bayesian, competitive equilibrium,
  mechanism-design implementability, and so on.
- **Driving force:** the one or two features of the environment that produce the main
  result, such as an information asymmetry, a commitment problem, or a complementarity.
  A good test is whether the result survives when that feature is removed.
- **Comparative statics:** the sign, what is held fixed, and whether the result is local
  or global.
- **Modeling choices:** which simplifications (functional forms, the number of types,
  the timing) are innocuous and which drive the result. Robustness sections and
  extensions usually answer this.

## 5. Statistical procedures and guarantees

- **Target and estimator:** the estimand, the estimator, and the conditions under which
  the estimator is consistent, asymptotically normal, efficient, or valid in finite
  samples.
- **The device:** what makes the method work. Examples are an orthogonal or doubly robust
  score, sample splitting or cross-fitting, exchangeability, a pivot, a concentration
  inequality, or a reduction to a known problem.
- **What is assumed about nuisance components:** rates, complexity (Donsker or
  otherwise), and correct specification.
- **Validity vs. efficiency vs. power:** which one the paper's guarantee concerns.
- **Simulations:** whether the designs probe the assumption boundary or only the
  favorable case.

## 6. Optimization and algorithms

- **Problem class:** convexity, smoothness, constraints, stochasticity.
- **Guarantee type:** convergence, rate, sample or iteration complexity, approximation
  ratio, and whether it is worst-case or average-case.
- **What is new:** the algorithm itself, the analysis, or the problem class it covers.
- **Lower bounds:** whether the rate is optimal, and in what sense.

## 7. Empirical translation

For theory meant to inform empirical work, say:

- Which observable implications the model has, and which of them are distinctive to
  this model rather than its competitors.
- What data or variation would test or calibrate it.
- What an applied researcher should change in practice because of this result.

## 8. Common misreadings

- Reporting an asymptotic result as if it held in finite samples.
- Dropping "under regularity conditions" when those conditions are restrictive.
- Confusing pointwise and uniform validity, or marginal and conditional coverage.
- Presenting a sufficient condition as necessary.
- Turning an existence result into a claim about a particular construction.
- Explaining the result with intuition that is not the mechanism the proof actually uses.
