# Empirical machine learning, algorithms, and computational papers

Load this guide when the contribution is a method, model, training or inference
procedure, system, or benchmark whose support is mainly experimental.

## Contents
1. Reconstructing the method
2. What the comparisons establish
3. Ablations and mechanism
4. Data, evaluation, and leakage
5. Resources and reproducibility
6. Applicability
7. Common misreadings

---

## 1. Reconstructing the method

- **The change:** relative to the strongest baseline or the closest predecessor, the
  component this method changes. Possibilities include the architecture, objective,
  data, training procedure, inference procedure, or retrieval. Give it in one sentence.
- **The rationale:** why the change should help, according to the authors. Treat it as
  their interpretation until the experiments show it.
- **Specification:** inputs, outputs, the loss or objective, and the key
  hyperparameters, written precisely enough to reimplement the core. Give pseudocode in
  a deep reading.
- **Inherited parts:** which components come unchanged from prior work. Credit them
  explicitly so the real change stands out.

## 2. What the comparisons establish

- **Held fixed:** data, model size, compute budget, tuning effort, and prompts or
  decoding settings across the methods compared. An unequal tuning budget is the most
  common hidden confound.
- **Baselines:** whether they are strong and current, and whether they were rerun or
  copied from other papers under different settings.
- **Uncertainty:** the number of seeds, variance or confidence intervals, and whether the
  gains exceed run-to-run noise.
- **Magnitude:** whether the improvement matters in practice, or is within benchmark
  saturation or noise.
- **Scope of claim:** state which datasets, scales, and domains the evidence covers, and
  don't let the conclusion go beyond them.

## 3. Ablations and mechanism

- Whether removing the proposed component removes the gain. That is the minimum
  evidence that the component causes it.
- Whether the ablations isolate the stated mechanism or only the overall package.
- Whether the analysis experiments (probing, visualization, scaling curves) test the
  authors' explanation, or only illustrate it.
- Which plausible alternative explanations remain, such as more compute, more data, or
  better tuning.

## 4. Data, evaluation, and leakage

- **Splits:** whether the train, validation, and test splits are clean. Check for
  temporal leakage, overlap between pretraining and test data (contamination), and
  selection of the best checkpoint on the test set.
- **Benchmark validity:** what the benchmark actually measures, and whether that
  matches the claim (a "reasoning" claim on a pattern-matching benchmark, for example).
- **Metrics:** whether the metric matches the goal, and whether human or LLM judges
  were used. Check how the judges were validated.
- **Distribution shift:** whether evaluation includes out-of-distribution or
  real-world conditions where the claim needs them.
- **Dataset or benchmark contributions:** reconstruct collection, sampling, annotation,
  quality control, licensing/access, and subgroup coverage. Distinguish the capability
  the benchmark measures from the performance of the baseline used to demonstrate it.
- **Agent evaluations:** preserve the tool environment, model/version, prompts, attempt
  budget, stopping rules, and success grader when they affect the result. Distinguish
  pass@k from single-attempt success and include latency or cost in efficiency claims.

## 5. Resources and reproducibility

- Compute, data access, and model access (open weights or API).
- Whether code and configurations are released.
- Details that the main text omits but the appendix or code reveals.
- Distinguish artifacts that are linked, artifacts you inspected (with a commit or
  release), and results actually reproduced. A working code link proves availability,
  not reproducibility. Resolve consequential paper/code differences explicitly.

## 6. Applicability

- When a practitioner should use this method instead of the baseline, and what it costs.
- The regimes (data size, model scale, domain) where the gain is expected to vanish or
  reverse.
- Which part of the idea transfers beyond this setting, which is the reusable tool for
  question 7.

## 7. Common misreadings

- Crediting the new component with a gain that came from scale, data, or tuning.
- Treating a single-seed result as reliable.
- Generalizing from one benchmark family to the whole capability.
- Accepting the authors' mechanism story when no ablation tests it.
- Missing that the baseline numbers come from a different setup.
