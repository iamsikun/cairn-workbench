# Empirical, causal, structural, experimental, and descriptive papers

Load this guide for papers whose contribution rests on data: causal estimates, structural
estimation, experiments, measurement, description, or qualitative analysis. Use only the
sections that match the paper.

## Contents
1. Causal empirical research
2. Inference and magnitude
3. Structural and decision models
4. Experiments (lab, field, online, natural science)
5. Measurement and descriptive work
6. Qualitative and case-based research
7. Common misreadings

---

## 1. Causal empirical research

**Estimand before estimator.** First state, in words, the causal quantity the paper is
after: ATE, ATT, LATE for compliers, a policy elasticity, a marginal effect at some
margin. Then describe the estimator separately. Many papers report a coefficient whose
estimand is narrower than the headline. IV recovers effects for compliers, for example,
and a staggered TWFE design can recover a weighted average with negative weights.

**Identifying variation.** Ask which comparison actually produces the number:

- Which units are compared, at what times, and why the comparison group stands in for
  the treated group's counterfactual.
- The source of variation: a policy change, a threshold, an instrument, timing,
  a lottery, or selection on observables.
- In one sentence, what would have to be true for the estimate to be biased. That
  sentence is the identifying assumption in plain words.

**Assumptions by design** (check whichever applies):

| Design | Key assumption | Typical evidence | What evidence cannot show |
|---|---|---|---|
| DiD / event study | Parallel trends in the counterfactual | Pre-trends, placebo outcomes | Post-period trend breaks unrelated to treatment |
| Staggered adoption | Homogeneous effects, or a heterogeneity-robust estimator | Comparison with Callaway–Sant'Anna, Sun–Abraham, etc. | — |
| IV | Relevance, exclusion, monotonicity | First stage F, balance on instrument | Exclusion, which is never directly testable |
| RD | Continuity at the cutoff, no manipulation | Density tests, covariate smoothness | Effects away from the cutoff |
| Selection on observables | Unconfoundedness + overlap | Balance, sensitivity analysis | Unobserved confounders |
| Synthetic control | Pre-period fit reflects shared factors | Pre-fit, placebo in space/time | — |

**Interpretation.** Separate what the estimate shows, such as "the policy raised Y by X
for this population," from the mechanism the authors propose. Mechanism evidence is
usually weaker: heterogeneity splits, mediators, and survey responses. Note which
mechanisms are tested and which are only asserted.

**External validity.** Name the population, period, institutional setting, and margin
of the effect. Ask whether the result is partial or general equilibrium.

## 2. Inference and magnitude

- **Sample construction:** trace the source population to the analysis sample, including
  exclusions, missingness, attrition, weighting, and changing sample sizes across
  specifications. These choices can change both the target population and the estimate.
- **Standard errors are choices.** Check the clustering level against the level of
  treatment assignment. With few clusters, check for wild bootstrap or randomization
  inference. Note any adjustments for multiple hypotheses.
- **Fixed effects and controls** change the comparison. Write out which variation is
  left after the fixed effects, and look for "bad controls" (post-treatment variables).
- **Statistical vs. practical significance.** Translate coefficients into economically
  meaningful units: a percent of the mean, a standard deviation, dollars, or a comparison
  with known effects. A precise zero can be an informative result.
- **Specification search.** Look for robustness tables that vary the things that matter,
  and for whether the main specification was pre-registered or chosen afterward.
- When tables are central, read the notes beneath them. Sample restrictions, units, and
  the precise dependent variable often appear only there.
- **Uncertainty:** distinguish SD, SE, confidence intervals, and credible intervals.
  Check whether a null result rules out substantively important effects rather than
  treating a large p-value as evidence of equivalence.

## 3. Structural and decision models

- **Primitives:** the agents, their choices, their objectives, their information, and
  the equilibrium or solution concept.
- **Identification:** which features of the data pin down each key parameter. Good
  papers state this informally ("the curvature parameter is identified from how demand
  responds to …"). If they don't, try to reconstruct it and label it as your inference.
- **Functional-form vs. data-driven identification:** which results would survive
  different distributional or functional assumptions.
- **Fit:** targeted moments vs. untargeted moments. Untargeted fit is the more
  informative validation.
- **Counterfactuals:** which primitives are held fixed, whether the counterfactual
  leaves the support of the data, and whether policy-invariance assumptions are
  plausible (the Lucas critique).
- Also apply `formal.md` for the model's analytical results.

## 4. Experiments (lab, field, online, natural science)

- **Units, randomization, assignment:** what was randomized, at what level, and with
  what stratification. Check compliance and attrition, and whether attrition differs by
  arm.
- **Controls:** what the control condition holds fixed, and whether the treatment
  bundles several changes together.
- **Measurement:** primary vs. secondary outcomes, pre-registration, and deviations from
  the pre-analysis plan.
- **Competing mechanisms:** which alternatives the design rules out, and which remain
  open. Look for demand effects, Hawthorne effects, and spillovers between units.
- **Lab/natural science:** replicates (biological vs. technical), blinding,
  dose-response, positive and negative controls, and the instrument's limits.

## 5. Measurement and descriptive work

- **What becomes observable:** the new dataset, measure, or fact, and why it could not
  be seen before.
- **Construct validity:** whether the measure captures the concept, how it was validated
  against ground truth, and how its known biases (coverage, selection into the sample,
  reporting) shape the facts.
- **Descriptive vs. causal language:** flag any sentence where a descriptive pattern is
  read causally.
- **Reusability:** whether others can build on the measure, given data access and code.

## 6. Qualitative and case-based research

- **Sources and access:** interviews, archives, ethnography, cases. How cases were
  selected, and what the selection allows the authors to conclude.
- **Analytical process:** coding scheme, saturation, triangulation, and any negative or
  disconfirming cases discussed.
- **Claims:** whether the paper builds theory (concepts, mechanisms) or tests it, and
  whether the claims stay within that scope.

## 7. Common misreadings

- Treating a LATE or a cutoff-local effect as a population average.
- Dropping "conditional on X" from a claim.
- Turning "no significant effect" into "no effect" without discussing power.
- Reading a mechanism as established when only one test supports it.
- Reporting a coefficient without its units or a meaningful benchmark.
- Missing that the preferred specification differs between the abstract and the main table.
