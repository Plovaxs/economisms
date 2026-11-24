# Literature map and scoped novelty statement (audit item SCI-01, partial)

**What this is.** A map from each task in this repository to the published work it should be compared with,
built on 24 November 2026 from 20 targeted lookups (one per work, by title and authors) with a general web
search tool. **What it is not:** a systematic review. No bibliographic database was searched, no query string was
run and screened, nothing was snowballed, no second reviewer checked it, and **no paper was read in full**: the
details below are bibliographic (authors, venue, volume, pages, DOI) and the one-line descriptions come from the
abstracts and summaries the search returned. Where a lookup did not confirm a detail, this file says so. The
audit's SCI-01 asks for a search protocol, inclusion criteria, a comparator matrix and a scoped novelty
statement; this file supplies the last two in draft and a draft of the first, and says what is missing.

**Verification level used below.** `V1`: the work exists and its citation details were confirmed in search
results on the date above. Nothing here is `V2` (read and checked against this repository's claims).

## Draft search protocol (to be run, not yet run)

Databases: Scopus, Web of Science, Google Scholar, SSRN, arXiv (q-fin, stat.ML, quant-ph), RePEc. Period: 1995
to the review date for methods, 2018 onward for neural and quantum methods. Inclusion: peer-reviewed or
working-paper studies that compare a learned model with an explicit classical baseline on the SAME task and
report the evaluation protocol; exclusion: studies that report only the proposed method. Draft strings:

- `("deep hedging" OR "reinforcement learning" AND hedging) AND ("transaction costs") AND (delta OR "no-trade" OR "Whalley")`
- `("physics-informed" OR "deep BSDE") AND ("Black-Scholes" OR "option pricing") AND (benchmark OR "finite difference")`
- `("inflation" AND (nowcast* OR forecast*)) AND ("machine learning") AND (benchmark OR "random walk" OR "base effect*")`
- `("value-at-risk" AND ("filtered historical simulation" OR GARCH)) AND (backtest* OR "conditional coverage")`
- `("quantum machine learning") AND (benchmark* AND "classical baseline*")`
- `("neural SDE" OR "neural stochastic differential") AND (macroeconomic OR financial)`

Two reviewers screen titles, then abstracts, then full texts; disagreements are logged; an extraction table
records the data, the baseline, the metric, the split and the result of every included study.

## Comparator matrix

| Task here | What the repository does | Reference points found (all `V1`) | Alignment and difference | Status |
| --- | --- | --- | --- | --- |
| Hedging (H5, E1) | A REINFORCE policy (82 parameters) against a delta hedge with a no-trade band, on simulated GBM paths with proportional costs. | Buehler, Gonon, Teichmann and Wood, "Deep hedging" (1); Whalley and Wilmott 1997 (2). | The baseline is the right family: (2) derives a hedging rule with a no-trade band for small costs, and later work cites its band width as O(λ^(1/3)). (1) trains networks against convex risk measures and reports beating a standard complete-market hedge in its own experiments. The repository also has a differentiable deep-hedge network (HDG-04) closer to (1); H5 concerns only the REINFORCE variant. | Not compared with (1)'s setup. |
| PDE solvers (H3) | Crank-Nicolson grid, a PINN and a deep BSDE on Black-Scholes, plus a basket generalisation. | Han, Jentzen and E, PNAS 2018 (3); Raissi, Perdikaris and Karniadakis, J. Comput. Phys. 2019 (4). | (3) tests a deep BSDE method on nonlinear Black-Scholes, Hamilton-Jacobi-Bellman and Allen-Cahn equations in high dimension, the regime where a grid's `M^d` cost bites; (4) is the standard PINN reference. The repository's finding that a grid wins in one dimension is not in conflict; its dimension-scaling claim is untested beyond what the PDE benchmark reports. | The crossover (M-04) is not measured. |
| Neural SDE (H2) | A drift and diffusion network on macro data, trained by likelihood and proper scoring, Euler-Maruyama and stochastic Heun solvers. | Kidger, Foster, Li, Oberhauser and Lyons, "Neural SDEs as infinite-dimensional GANs", ICML 2021 (5). | (5) trains neural SDEs as the generator of a Wasserstein GAN; the repository does not use that objective and is not compared with it. | Different construction; not compared. |
| Inflation nowcast (Finding 18, E2) | Base-effect rule, ridge and a small MLP against persistence of the year-over-year rate. | Atkeson and Ohanian, FRB Minneapolis Quarterly Review 2001 (6); Medeiros, Vasconcelos, Veiga and Zilberman, JBES 2021 (7). | (6) finds that Phillips-curve forecasts did not beat a naive one-year-ago benchmark, which is the baseline this repository found hard to beat too. (7) reports that machine-learning methods with MANY covariates beat benchmarks, random forests best; this repository's predictor set is small, so its "a learned model adds little" is not evidence against (7). | Not comparable in scope. |
| Value at risk (Finding 15, E3) | 250-day historical simulation, EWMA, GARCH with normal and filtered-historical-simulation quantiles, a neural volatility model; Kupiec and Christoffersen tests, pinball and QLIKE losses, moving-block bootstrap. | Kupiec, FEDS 95-24 (8); Christoffersen 1998 (9); Barone-Adesi, Giannopoulos and Vosper 1999 (10); Gneiting 2011 (11); Patton 2011 (12); Künsch 1989 (13). | These ARE the standard tools: (8) and (9) the coverage tests, (10) the filtered-historical-simulation method, (11) why the pinball loss is the consistent score for a quantile, (12) why QLIKE is robust for volatility forecasts, (13) the block bootstrap. One source in the lookups reports that the proportion-of-failures test has low power; E3's power note finds the same for a modest miscalibration under its exact-binomial criterion. | Aligned with the literature's tools. |
| Forecast comparison | Paired block-bootstrap intervals on loss differences; no Diebold-Mariano test. | Diebold and Mariano, JBES 1995 (14); Hewamalage, Ackermann and Bergmeir, DMKD 2023 (15). | The audit asks for Diebold-Mariano tests; the repository uses bootstrap intervals instead and has not implemented (14). (15) lists weak benchmarks and data leakage as the pitfalls that make weak methods look competitive, which is what the data-use audit looked for. | DM test not implemented. |
| Recession classification (H1, Finding 12) | Logistic, classical MLP and hybrid quantum models on NBER labels and factor features; the term spread added as a feature. | Estrella and Mishkin, REStat 1998 (16). | (16) reports the yield-curve slope as the strongest predictor beyond about two quarters ahead; the repository's Finding 12 (adding it made things worse) is its own result and is not a replication of (16). | Not compared. |
| Machine learning in finance | Small samples, simple baselines first. | Gu, Kelly and Xiu, RFS 2020 (17). | (17) reports trees and neural networks best at predicting returns on a large panel, so the "complexity does not help" pattern here is about small samples and these tasks, not a general claim. | Scope difference. |
| Quantum against classical (H1) | Hybrid circuit models against parameter-matched classical ones. | Bowles, Ahmed and Schuld, arXiv:2403.07059 (18). | (18) compared 12 quantum models against classical ones on 6 binary tasks and found the classical baselines generally better on small datasets. The repository's null result is consistent with that, and is not independent evidence for it. | Consistent; not independent. |
| Policy simulation (MARL) | PPO household and firm policies in a ledger-based economy. | Zheng, Trott, Srinivasa, Parkes and Socher, Science Advances 2022 (19). | (19) is a two-level deep RL framework for tax policy; the repository's environment is simpler and is not compared with it. | Not compared. |
| Evaluating RL | Multi-seed runs; E1 uses 50 fresh seeds. | Henderson, Islam, Bachman, Pineau, Precup and Meger, AAAI 2018 (20). | (20) argues that reported deep-RL results vary enough across runs that a method's gains are hard to judge, and proposes reporting guidelines; multi-seed reporting is in line with that. | Aligned. |

## Scoped novelty statement

What this repository can honestly claim: one executable, tested platform covering these tasks; negative and null
results disclosed with their evidence trail; defects found and fixed with pinned regression tests (the GDP
look-ahead, the `rsample` bug that zeroed a policy gradient, a boundary-month labelling bug); and a written evidence
discipline. **It does not claim a new method or a result that is new to the literature.** Several of its findings
are consistent with published ones (a naive baseline is hard to beat in inflation forecasting; classical models
tend to beat quantum ones on small datasets) and say nothing independent about them. Whether any single finding
is new is **unknown** until the protocol above is run, and an honest answer may be that none is.

## What is missing for SCI-01 to be complete

A run of the search protocol with the strings and dates recorded; screening by two people; full-text reading of
the comparators (everything here is `V1`); an extraction table; and a decision, per finding, of "new", "replicates"
or "contradicts". That is a reviewer's task, ideally the external reviewer the roadmap asks for.

## References (details as returned by the lookups; full texts not read)

1. H. Buehler, L. Gonon, J. Teichmann, B. Wood, "Deep hedging", *Quantitative Finance* 19(8), 1271-1291, 2019, DOI 10.1080/14697688.2019.1571683. [arXiv 1802.03042](https://arxiv.org/abs/1802.03042).
2. A. E. Whalley, P. Wilmott, "An asymptotic analysis of an optimal hedging model for option pricing with transaction costs", *Mathematical Finance* 7(3), 307-324, 1997, DOI 10.1111/1467-9965.00034. [RePEc](https://ideas.repec.org/a/bla/mathfi/v7y1997i3p307-324.html).
3. J. Han, A. Jentzen, W. E, "Solving high-dimensional partial differential equations using deep learning", *PNAS* 115(34), 8505-8510, 2018, DOI 10.1073/pnas.1718942115. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6112690).
4. M. Raissi, P. Perdikaris, G. E. Karniadakis, "Physics-informed neural networks: A deep learning framework for solving forward and inverse problems involving nonlinear partial differential equations", *Journal of Computational Physics* 378, 686-707, 2019, DOI 10.1016/j.jcp.2018.10.045. [Brown](https://neuralfields.cs.brown.edu/paper_4.html).
5. P. Kidger, J. Foster, X. Li, H. Oberhauser, T. Lyons, "Neural SDEs as infinite-dimensional GANs", *ICML 2021*, PMLR 139, 5453-5463. [PMLR](https://proceedings.mlr.press/v139/kidger21b.html).
6. A. Atkeson, L. E. Ohanian, "Are Phillips curves useful for forecasting inflation?", *Federal Reserve Bank of Minneapolis Quarterly Review* 25(1), 2-11, Winter 2001. [Minneapolis Fed](https://minneapolisfed.org/research/quarterly-review/are-phillips-curves-useful-for-forecasting-inflation).
7. M. C. Medeiros, G. F. R. Vasconcelos, Á. Veiga, E. Zilberman, "Forecasting inflation in a data-rich environment: the benefits of machine learning methods", *Journal of Business & Economic Statistics* 39(1), 98-119, 2021, DOI 10.1080/07350015.2019.1637745. [RePEc](https://ideas.repec.org/a/taf/jnlbes/v39y2021i1p98-119.html).
8. P. H. Kupiec, "Techniques for verifying the accuracy of risk measurement models", Federal Reserve Board FEDS Working Paper 95-24, 1995. [RePEc](https://econpapers.repec.org/RePEc:fip:fedgfe:95-24). *The lookup did not confirm a journal version.*
9. P. F. Christoffersen, "Evaluating interval forecasts", *International Economic Review* 39(4), 841-862, 1998. [RePEc](https://ideas.repec.org/a/ier/iecrev/v39y1998i4p841-62.html).
10. G. Barone-Adesi, K. Giannopoulos, L. Vosper, "VaR without correlations for portfolios of derivative securities", *Journal of Futures Markets* 19(5), 583-602, 1999. [RePEc](https://ideas.repec.org/a/wly/jfutmk/v19y1999i5p583-602.html).
11. T. Gneiting, "Making and evaluating point forecasts", *Journal of the American Statistical Association* 106(494), 746-762, 2011, DOI 10.1198/jasa.2011.r10138. [arXiv 0912.0902](https://arxiv.org/abs/0912.0902).
12. A. J. Patton, "Volatility forecast comparison using imperfect volatility proxies", *Journal of Econometrics* 160(1), 246-256, 2011, DOI 10.1016/j.jeconom.2010.03.034. [RePEc](https://econpapers.repec.org/RePEc:eee:econom:v:160:y:2011:i:1:p:246-256).
13. H. R. Künsch, "The jackknife and the bootstrap for general stationary observations", *Annals of Statistics* 17(3), 1217-1241, 1989, DOI 10.1214/aos/1176347265. [Project Euclid](https://projecteuclid.org/euclid.aos/1176347265).
14. F. X. Diebold, R. S. Mariano, "Comparing predictive accuracy", *Journal of Business & Economic Statistics* 13(3), 253-263, 1995. [RePEc](https://econpapers.repec.org/RePEc:bes:jnlbes:v:13:y:1995:i:3:p:253-63).
15. H. Hewamalage, K. Ackermann, C. Bergmeir, "Forecast evaluation for data scientists: common pitfalls and best practices", *Data Mining and Knowledge Discovery* 37, 788-832, 2023, DOI 10.1007/s10618-022-00894-5. [arXiv 2203.10716](https://arxiv.org/abs/2203.10716).
16. A. Estrella, F. S. Mishkin, "Predicting U.S. recessions: financial variables as leading indicators", *Review of Economics and Statistics* 80(1), 45-61, 1998. [RePEc](https://ideas.repec.org/a/tpr/restat/v80y1998i1p45-61.html).
17. S. Gu, B. Kelly, D. Xiu, "Empirical asset pricing via machine learning", *Review of Financial Studies* 33(5), 2223-2273, 2020, DOI 10.1093/rfs/hhaa009. [NBER](https://nber.org/papers/w25398).
18. J. Bowles, S. Ahmed, M. Schuld, "Better than classical? The subtle art of benchmarking quantum machine learning models", arXiv:2403.07059, 2024. [arXiv](https://arxiv.org/abs/2403.07059).
19. S. Zheng, A. Trott, S. Srinivasa, D. C. Parkes, R. Socher, "The AI Economist: Taxation policy design via two-level deep multiagent reinforcement learning", *Science Advances* 8(18), eabk2607, 2022, DOI 10.1126/sciadv.abk2607. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9067926).
20. P. Henderson, R. Islam, P. Bachman, J. Pineau, D. Precup, D. Meger, "Deep reinforcement learning that matters", *Proceedings of the AAAI Conference on Artificial Intelligence* 32, 2018, DOI 10.1609/aaai.v32i1.11694. [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/11694).
