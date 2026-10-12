# Metric Definitions — what every number in this report means

> Generated from `portfolio_model/src/metric_glossary.py` by `portfolio_model/scripts/build_definitions_doc.py`.
> The web UI **Definitions** tab and the workbook **Definitions** sheet render the same entries, so the three views can never disagree.

## How to use this page

1. **Start with the question, not the metric.** "Can the 2033 reserve be funded?" is answered by *Probability all reserve payments funded*, not by the median terminal value.
2. **Read the basis and the horizon before comparing two numbers.** Monthly VaR and terminal VaR are not the same measurement.
3. **Prefer ranges to point estimates.** Every percentile row exists because a single number is the wrong basis for a decision.
4. **When two engines disagree, that is a finding.** The comparison and disagreement sheets exist to make the disagreement visible, not to average it away.
5. **Assumptions are configurable, and they are the real drivers.** Expected returns, inflation, the reserve discount rate and the glide path move the conclusions far more than the choice of engine.

Quick index: [Inputs and assumptions](#inputs-and-assumptions) · [Historical portfolio metrics](#historical-portfolio-metrics) · [Plan mechanics (money in, obligation out)](#plan-mechanics-money-in-obligation-out) · [Simulation outcomes](#simulation-outcomes) · [The three engines and why they disagree](#the-three-engines-and-why-they-disagree) · [Risk measures (VaR and CVaR)](#risk-measures-var-and-cvar) · [Sensitivity and stress](#sensitivity-and-stress) · [Stops and optimisation](#stops-and-optimisation) · [Suggestions: how the rule flags work](#suggestions:-how-the-rule-flags-work) · [Data quality and what the model refuses to invent](#data-quality-and-what-the-model-refuses-to-invent) · [Rule caps and thresholds (what the flags compare against)](#rule-caps-and-thresholds-what-the-flags-compare-against) · [Scorecard](#scorecard)

## 1. Inputs and assumptions

Everything downstream depends on these. If a number later in the report surprises you, it is usually because one of these was not what you assumed.

### Weights source

*Glossary key: `weights_source` · unit: text*

- **What it is:** Which input column was used: explicit portfolio weights, market value / total, or quantity x price.
- **What it measures:** Tells you the origin of the allocation the whole model is built on.
- **How to read it for this portfolio:** If it says 'supplied weights', the analysis is about the allocation you wrote down. If it says 'derived from market value', it reflects your actual positions today.
- **What to do about it:** If the source is not what you intended, fix the spreadsheet column rather than the model.
- **Trap:** Weights are renormalised to 100%. If your weights summed to 92%, everything is scaled up by 8.7% silently.

### Expected return (annual)

*Glossary key: `expected_return` · unit: pct*

- **What it is:** Spreadsheet 'Expected Return' column when present and expected_returns.source = input; otherwise the historical mean compounded to a year, shrunk toward the cross-asset mean by expected_returns.shrinkage.
- **What it measures:** The central return assumption driving every simulation.
- **How to read it for this portfolio:** This is the single most influential number in the whole report. A 1pp change moves the median 2033 outcome by roughly the horizon length in years.
- **What to do about it:** Sanity-check it against the historical column on the same row. If your assumption is far above history, say why in the thesis.
- **Trap:** It is an assumption, not a forecast. The engines are not predicting; they are answering 'what follows from these assumptions'.

### Volatility (annual)

*Glossary key: `volatility` · unit: pct*

- **What it is:** Standard deviation of monthly returns x sqrt(12).
- **What it measures:** How widely a holding's monthly returns scatter around their average.
- **How to read it for this portfolio:** 20% annual volatility means roughly two-thirds of months land within +/-5.8% of the average month. It measures dispersion, not the chance of losing money.
- **What to do about it:** If volatility is understated, drawdown and CVaR numbers are understated too.
- **Trap:** Volatility from a short history (see confidence) is unreliable, and it treats upside and downside moves identically.

### Risk-free rate

*Glossary key: `risk_free_rate` · unit: pct*

- **What it is:** Config risk.risk_free_rate; also used as the return earned by the CASH holding every period.
- **What it measures:** The floor return and the discount rate reference for Sharpe-style ratios.
- **How to read it for this portfolio:** Cash is never modelled as 0% return; it earns this rate. Raising it raises cash-heavy portfolios.
- **What to do about it:** Set it near the current 3-month T-bill yield for the competition year you are modelling.
- **Trap:** Sharpe here divides raw return by volatility (no risk-free subtraction), so it is a risk-adjusted *ratio*, not the textbook excess-return Sharpe.

### Inflation assumption

*Glossary key: `inflation_base` · unit: pct*

- **What it is:** Config risk.inflation_base, applied to convert nominal capital into 'real capital' for floor tests.
- **What it measures:** The price-level assumption behind every 'real' or 'above floor' probability.
- **How to read it for this portfolio:** Real success is always lower than nominal success. The gap between the two is the cost of ignoring inflation.
- **What to do about it:** Run the inflation_scenarios list rather than arguing about one number.
- **Trap:** Returns are nominal; only the success thresholds are inflation-adjusted. The model does not deflate the return series.

## 2. Historical portfolio metrics

These describe what the *current weights* would have done over the price history. They are a hypothetical portfolio, not your account statement.

### Historical CAGR

*Glossary key: `cagr_historical` · unit: pct*

- **What it is:** (final index value / first index value)^(1 / years) - 1, on the rebalanced current-weight index.
- **What it measures:** The single compound growth rate that would have reproduced the past exactly.
- **How to read it for this portfolio:** A smoothed average of what this allocation actually did. Compare it with the simulated median to see whether your assumptions are optimistic or conservative.
- **What to do about it:** If simulated median >> historical CAGR, your expected returns are aggressive; check the sensitivity grid.
- **Trap:** It is path-dependent and start-date dependent. It also assumes today's weights had been held the whole time (rebalanced index), which is a hypothetical, not your real account.

### Mean annual return (historical)

*Glossary key: `mean_annual_return` · unit: pct*

- **What it is:** (1 + average monthly return)^12 - 1.
- **What it measures:** The average month, annualised by compounding.
- **How to read it for this portfolio:** Higher than CAGR whenever returns were volatile, because volatility drags compounding down.
- **What to do about it:** Use CAGR for outcome questions and mean return for expectation questions.
- **Trap:** Mean annual return minus CAGR is roughly the volatility drag: never quote the mean as if it were achievable growth.

### Volatility (historical, annual)

*Glossary key: `annual_volatility` · unit: pct*

- **What it is:** Standard deviation of portfolio monthly returns x sqrt(12).
- **What it measures:** Size of typical month-to-month swings in the current-weight portfolio.
- **How to read it for this portfolio:** Roughly 1 in 6 months lands outside +/-1 annual-volatility/3.6 of the average month.
- **What to do about it:** Compare against your own tolerance: if 20%+ annual volatility feels unholdable, the simulation will not feel reassuring either.
- **Trap:** Portfolio volatility is not the weighted average of holding volatilities; correlation is what makes it lower.

### Sharpe (historical)

*Glossary key: `sharpe` · unit: ratio*

- **What it is:** Mean annual return / annual volatility.
- **What it measures:** Return earned per unit of swing taken.
- **How to read it for this portfolio:** Above ~0.6 for a stock/bond portfolio is respectable; below ~0.25 means the extra return is not paying for the volatility.
- **What to do about it:** A low Sharpe with high volatility argues for trimming the noisiest positions, not for adding return.
- **Trap:** No risk-free subtraction here, and it is computed on history. Two portfolios with the same Sharpe can have completely different drawdown shapes.

### Sortino (historical)

*Glossary key: `sortino` · unit: ratio*

- **What it is:** Mean annual return / downside deviation (std of negative months only, x sqrt(12)).
- **What it measures:** Return per unit of *bad* movement; upside is not penalised.
- **How to read it for this portfolio:** Sortino > Sharpe whenever upside is large. A big gap means the volatility is mostly good news.
- **What to do about it:** Use it when a holding has lumpy upside (growth names) and you care only about downside.
- **Trap:** With few negative months the downside deviation is noisy and Sortino looks flattering.

### Downside deviation

*Glossary key: `downside_deviation` · unit: pct*

- **What it is:** Standard deviation of negative monthly returns x sqrt(12).
- **What it measures:** How violent the losing months are.
- **How to read it for this portfolio:** This is the number that maps to how the portfolio actually feels to hold.
- **What to do about it:** If downside deviation is close to total volatility, the portfolio has little upside cushion.
- **Trap:** Counts only months below zero, so it ignores how *often* you lose.

### Max drawdown (historical)

*Glossary key: `max_drawdown` · unit: pct*

- **What it is:** Minimum of (value / running peak - 1) on the rebalanced index.
- **What it measures:** The deepest peak-to-trough fall actually experienced.
- **How to read it for this portfolio:** The realistic test of whether you could have held. -35% is survivable for a long horizon; -60% usually is not.
- **What to do about it:** Compare with the simulated median max drawdown: if history was much worse than the simulation, the model is optimistic.
- **Trap:** One event defines it. It says nothing about how long the recovery took (see the recovery table) and nothing about drawdowns that started after the trough.

### Drawdown peak / trough / recovery dates

*Glossary key: `drawdown_peak_trough_recovery` · unit: text*

- **What it is:** Date of the running peak before the worst trough, the trough date, and the first date the index exceeded the peak again.
- **What it measures:** The shape of the worst episode: how fast it fell and how long you waited.
- **How to read it for this portfolio:** Depth plus time-underwater is the real pain. A -30% drawdown recovered in 6 months is a different risk from one that took 4 years.
- **What to do about it:** Use the recovery column on the Risk sheet when arguing about time horizon.
- **Trap:** A blank recovery means the index had not recovered by the end of the data - not that it never will.

### Days to recover (drawdown events)

*Glossary key: `recovery_days` · unit: days*

- **What it is:** Calendar days from each trough (deeper than -5%) back to zero drawdown.
- **What it measures:** How long a drawdown kept you below your previous high.
- **How to read it for this portfolio:** Long recoveries are the argument for the glide path into 2033.
- **What to do about it:** If a plausible event's recovery is longer than the years left before the reserve phase, de-risk earlier.
- **Trap:** Events shallower than -5% are not listed, so the table understates small-but-frequent pain.

### Correlation (pairwise, monthly)

*Glossary key: `correlation` · unit: ratio*

- **What it is:** Pearson correlation of monthly returns between two holdings over the full history.
- **What it measures:** Whether two holdings move together, which is what decides if they are really two bets or one.
- **How to read it for this portfolio:** +0.9 means they are effectively the same position split in two. Below +0.4 they genuinely diversify. Negative correlation is a hedge.
- **What to do about it:** Above the configured correlation_threshold, size the pair as one exposure (the rule engine flags it).
- **Trap:** Correlation is estimated on history and rises toward 1.0 exactly when you need it not to.

### Correlation cluster

*Glossary key: `correlation_cluster` · unit: text*

- **What it is:** Single-linkage grouping of holdings joined by correlation above the threshold.
- **What it measures:** The set of holdings that behave like one bet.
- **How to read it for this portfolio:** A cluster of four names at 20% each is a 80% single-bet portfolio wearing four labels.
- **What to do about it:** Apply the correlated-group cap to the cluster, not to each member.
- **Trap:** Single-linkage can chain A-B and B-C into one cluster even when A-C correlation is modest.

### HHI (concentration index)

*Glossary key: `hhi` · unit: pct*

- **What it is:** Sum of squared weights. Normalised version: (HHI - 1/n) / (1 - 1/n).
- **What it measures:** How much of the portfolio sits in a few positions.
- **How to read it for this portfolio:** Raw HHI 0.25 means the concentration of an equal-weighted 4-holding portfolio. Normalised HHI 0 = perfectly spread, 1 = all in one name.
- **What to do about it:** Use it to argue concentration quantitatively instead of saying 'it feels concentrated'.
- **Trap:** HHI sees position size only. Two 25% positions in perfectly correlated names look the same as two independent names.

### Effective number of independent bets

*Glossary key: `effective_n` · unit: count*

- **What it is:** 1 / HHI, where HHI is the sum of squared weights over all holdings with weight > 0.
- **What it measures:** How many truly separate bets the weighting is equivalent to.
- **How to read it for this portfolio:** 7 holdings with effective_n 3.4 is a three-bet portfolio. This is the most honest diversification number in the report.
- **What to do about it:** The rule engine flags it when effective_n falls below 60% of the holding count.
- **Trap:** It measures weight concentration, not correlation-adjusted independence, so it is an upper bound on real diversification.

### Top 3 / 5 / 10 weight

*Glossary key: `top3_top5_top10` · unit: pct*

- **What it is:** Sum of the largest three, five and ten weights.
- **What it measures:** How much of the portfolio the biggest names control.
- **How to read it for this portfolio:** Top 3 above 60% means three decisions dominate the outcome, whatever the rest of the sheet says.
- **What to do about it:** Compare against max_position_weight and max_sector_weight.
- **Trap:** With fewer than 3 holdings the top-3 figure is simply 100%.

## 3. Plan mechanics (money in, obligation out)

The simulation is a schedule, not a generic forecast. These are the schedule's parts.

### Invested capital / contributions

*Glossary key: `contributions` · unit: money*

- **What it is:** Sum of cashflows.contributions amounts (default 2027: $300,000, 2028: $150,000).
- **What it measures:** The money the simulation starts compounding, and the reference point for every success probability.
- **How to read it for this portfolio:** Every 'success' number is measured against this figure, so changing it changes all probabilities.
- **What to do about it:** Confirm it matches the competition's actual funding schedule before reading any probability.
- **Trap:** Contributions are invested at the current glide-path target weights at that month, not at today's holdings weights.

### Required reserve (present value)

*Glossary key: `required_reserve` · unit: money*

- **What it is:** Payment x [1 - (1+r)^-n] / r x (1+r) for n = last_year - first_year + 1 payments at rate = reserve_discount_rate (annuity-due).
- **What it measures:** The lump sum needed today to fund the scheduled payments, assuming the reserve keeps earning the discount rate.
- **How to read it for this portfolio:** This is the hard obligation the 2033 split must cover. Everything above it is the facility contribution.
- **What to do about it:** If the discount rate is wrong, the obligation is wrong: 2.9% here, so test 2% and 4% before committing.
- **Trap:** It is a present value, not cash you must hold. A reserve exactly equal to it only works if the reserve keeps earning that rate.

### 2033 split

*Glossary key: `split_month` · unit: money*

- **What it is:** At the start of the glide-end year: reserve = min(value, required_reserve); facility = value - required_reserve.
- **What it measures:** The moment the portfolio is cut into the obligation and the surplus.
- **How to read it for this portfolio:** A negative facility means the portfolio cannot cover the reserve at 2033 - the core failure mode of the plan.
- **What to do about it:** Read prob_facility_negative before reading any terminal percentile.
- **Trap:** The split is a modelling convention (one clean cut), not a legal or tax event.

### Facility contribution

*Glossary key: `facility_contribution` · unit: money*

- **What it is:** Terminal value at 2033 minus required reserve, per simulation.
- **What it measures:** What is left for the facility after the reserve obligation is met.
- **How to read it for this portfolio:** Its 5th percentile is the number to plan against; its median is the number to hope for.
- **What to do about it:** Report it as a range (p5 to p95), never as a single figure.
- **Trap:** Negative values are real outcomes, not errors - they are the shortfall cases.

### Glide path targets

*Glossary key: `glide_path` · unit: pct*

- **What it is:** Year-by-year equity/bond/cash targets from glide_path.method between start_equity and end_equity.
- **What it measures:** The planned de-risking schedule into the payment phase.
- **How to read it for this portfolio:** The equity share each year is what the simulation rebalances toward; it is the model's main risk control.
- **What to do about it:** Compare the glide variants table: it re-runs the simulation with no glide path, linear, accelerating and custom.
- **Trap:** Glide path changes risk, not expected return much. Its value shows up in drawdown and reserve-funding probabilities, not in the median.

### Rebalancing band

*Glossary key: `rebalance_band` · unit: pct*

- **What it is:** Absolute: target +/- band percentage points. Relative: target x (1 +/- relative_band).
- **What it measures:** How far a class may drift before the model forces a trade.
- **How to read it for this portfolio:** Tight bands mean more trades and more transaction cost; loose bands mean the glide path is advisory only.
- **What to do about it:** Check mean_turnover and mean_rebalances to see what the band actually costs.
- **Trap:** Bands are tested on asset *class* weights at month end, not on individual holdings.

### Turnover / rebalances (mean)

*Glossary key: `turnover` · unit: money*

- **What it is:** Sum over time of absolute weight changes per simulation; mean across simulations.
- **What it measures:** How much trading the policy actually requires.
- **How to read it for this portfolio:** High turnover with tiny benefit means the band is too tight.
- **What to do about it:** Weigh it against transaction_cost and the tax friction the competition cares about.
- **Trap:** Turnover is not a cost. The cost is turnover x transaction_cost, already netted out of values.

## 4. Simulation outcomes

The numbers people quote. Each one answers a different question, and quoting the wrong one is how portfolios get mis-sized.

### Terminal value (2033)

*Glossary key: `terminal_2033` · unit: money*

- **What it is:** Portfolio value at the end of the growth phase (month before the glide-end year), per simulation.
- **What it measures:** The outcome the whole plan is judged on.
- **How to read it for this portfolio:** Read the distribution, not the average: p5 is the planning case, p50 the expected case, p95 the lucky case.
- **What to do about it:** Any decision that only works at p50 is not a decision, it is a bet.
- **Trap:** It is measured *before* the 2033-2042 payments are made, so it is not the money you end with.

### Median terminal value

*Glossary key: `median_terminal` · unit: money*

- **What it is:** 50th percentile of simulated 2033 values.
- **What it measures:** The middle outcome: half the simulations land below it.
- **How to read it for this portfolio:** The headline number. Compare it across engines - if Monte Carlo and bootstrap disagree by more than 25%, the distribution shape is doing the work.
- **What to do about it:** Use it for expectation, never for sizing an obligation.
- **Trap:** Median is not mean. With fat tails the mean is higher than the median, and the median is the safer one to quote.

### Terminal percentiles (p5 ... p95)

*Glossary key: `terminal_percentiles` · unit: money*

- **What it is:** Percentiles of the simulated 2033 value distribution.
- **What it measures:** The full range of plausible outcomes.
- **How to read it for this portfolio:** p5 is the case you must survive; p95 is the case you must not plan for.
- **What to do about it:** Fund obligations from p5-p10, plan spending from p50.
- **Trap:** Percentiles from 10,000 simulations are stable to roughly +/-0.5pp in probability terms, not to the dollar.

### Success: terminal > contributions

*Glossary key: `prob_terminal_gt_start` · unit: pct*

- **What it is:** Share of simulations where 2033 value > total contributions (nominal).
- **What it measures:** The plain 'did the money grow' probability.
- **How to read it for this portfolio:** 92% sounds safe, but it is a nominal test against a 2027-28 figure.
- **What to do about it:** Always read it next to prob_terminal_gt_real_start.
- **Trap:** Growing money in nominal terms while losing purchasing power still counts as success here.

### Success above real capital

*Glossary key: `prob_terminal_gt_real_start` · unit: pct*

- **What it is:** Share of simulations where 2033 value > contributions x (1 + inflation)^(years to 2033).
- **What it measures:** Did the portfolio beat inflation as well as the contributions?
- **How to read it for this portfolio:** This is the honest success number. The gap to the nominal version is the inflation tax.
- **What to do about it:** Use it as the headline in anything judged by a committee.
- **Trap:** It uses one inflation assumption; the scenario rows show the sensitivity.

### Capital-floor probabilities

*Glossary key: `prob_floor_100 / 90 / 80 / 70` · unit: pct*

- **What it is:** Share of simulations where terminal value >= floor x inflation-adjusted contributions, for floors 100%, 90%, 80%, 70%.
- **What it measures:** How likely the plan is to preserve at least a given fraction of real purchasing power.
- **How to read it for this portfolio:** A ladder, not a verdict: 95% chance of keeping 80% of real capital is a very different claim from 95% chance of keeping all of it.
- **What to do about it:** Choose the floor the competition's mandate actually requires, then read only that row.
- **Trap:** Floors are relative to contributions, not to the reserve obligation.

### Probability all reserve payments funded

*Glossary key: `prob_all_payments_funded` · unit: pct*

- **What it is:** Share of simulations where the reserve balance never goes below zero at any of the 10 payment dates.
- **What it measures:** Whether the obligation is actually met on time, every time.
- **How to read it for this portfolio:** The most decision-relevant number in the report. The bootstrap version is the one to plan against.
- **What to do about it:** Below the 90% rule threshold the engine raises a HIGH funding flag: extend the glide path, raise the buffer, or shrink payments.
- **Trap:** It requires the reserve to be intact at each payment date; a simulation that ends solvent but was empty in 2037 still fails.

### Probability the facility gets nothing

*Glossary key: `prob_facility_negative` · unit: pct*

- **What it is:** Share of simulations where 2033 value < required reserve.
- **What it measures:** How often the plan covers the obligation but has nothing left over.
- **How to read it for this portfolio:** High values mean the reserve is eating the whole portfolio by 2033.
- **What to do about it:** Treat this as the shortfall probability for the facility's own goals.
- **Trap:** Markov reports it as 1 - P(facility negative) in the comparison table; check the label before comparing rows.

### Probability of capital depletion

*Glossary key: `prob_capital_depletion` · unit: pct*

- **What it is:** Share of simulations where the 2033 value is essentially zero.
- **What it measures:** Total-loss probability under the model's assumptions.
- **How to read it for this portfolio:** Usually near zero for a diversified stock/bond/cash mix. If it is not, the return assumptions or the model choice are extreme.
- **What to do about it:** Treat a non-trivial value as a signal to check the Student-t degrees of freedom or the volatility multiplier.
- **Trap:** Zero here means the model's distribution produced a catastrophic path; real total loss also comes from forced selling, which is not modelled.

### Max drawdown (growth phase)

*Glossary key: `max_drawdown_growth` · unit: pct*

- **What it is:** Deepest peak-to-trough fall in each simulated path before the 2033 split; reported as a median and as probabilities of exceeding 10/20/30/40%.
- **What it measures:** How painful the ride to 2033 is likely to be.
- **How to read it for this portfolio:** Median max drawdown is the typical experience; P(>20%) is the trigger for a portfolio review.
- **What to do about it:** Above the 25% review trigger the engine raises a drawdown flag.
- **Trap:** Measured on the growth phase only. Reserve-phase drawdowns are deliberately excluded because that money is already earmarked.

### Expected CAGR (Monte Carlo)

*Glossary key: `cagr_money_weighted` · unit: pct*

- **What it is:** (median terminal / total contributions)^(1 / years to 2033) - 1.
- **What it measures:** The annual growth rate implied by the median outcome against the money put in.
- **How to read it for this portfolio:** The bridge between the simulation and an intuitive rate. Compare it with historical CAGR to see how aggressive the assumptions are.
- **What to do about it:** If it is well above historical CAGR, say out loud what justifies the gap.
- **Trap:** It uses contributions as the base, so a mid-period contribution drags it below the portfolio's own return.

### 2031 sponsor checkpoint

*Glossary key: `v2031 / projected_facility_2031` · unit: money*

- **What it is:** Percentiles of portfolio value at the start of 2031, and of value minus required reserve.
- **What it measures:** An early warning read: how the plan looks two years before the split.
- **How to read it for this portfolio:** The projected-facility p5 at 2031 is the earliest honest signal that the reserve is at risk.
- **What to do about it:** Use it as the decision date for accelerating the glide path.
- **Trap:** It is a snapshot, not a promise; two more years of market risk remain after it.

## 5. The three engines and why they disagree

Three engines share one path simulator and differ only in where the returns come from. Their disagreement is information, not noise.

### Monte Carlo engine

*Glossary key: `monte_carlo` · unit: text*

- **What it is:** Monthly returns drawn from a parametric distribution (gaussian | lognormal | student_t | historical_residual) with the estimated mean vector and covariance, then run through the shared path engine.
- **What it measures:** What the plan does under a clean statistical model of the assumptions.
- **How to read it for this portfolio:** Smooth, symmetric (unless Student-t), and only as good as the mean/covariance you fed it.
- **What to do about it:** Run gaussian and student_t side by side; the difference is the price of assuming normal returns.
- **Trap:** Gaussian Monte Carlo systematically understates crash frequency. Never use it alone for a reserve obligation.

### Student-t simulation

*Glossary key: `student_t` · unit: text*

- **What it is:** Same covariance, with each month scaled by sqrt(dof / chi-square(dof)); dof = simulation.student_t_dof.
- **What it measures:** The same assumptions with fatter tails.
- **How to read it for this portfolio:** Lower p5, higher CVaR, lower reserve-funding probability than gaussian - and closer to how markets actually behave.
- **What to do about it:** Use dof 4-5 for equity-heavy portfolios; dof 3 is aggressive.
- **Trap:** Fat tails also raise the variance of the estimate; you need more simulations for stable percentiles.

### Historical bootstrap engine

*Glossary key: `bootstrap` · unit: text*

- **What it is:** Each simulation concatenates contiguous blocks of real historical joint daily returns (block bootstrap, block_size_days) covering the horizon, compounded to months, then run through the same path engine.
- **What it measures:** What the plan would have done if the future repeated stretches of the actual past, including 2008 and 2020.
- **How to read it for this portfolio:** The reality check. It carries real crashes and real correlation behaviour, so it is usually the more conservative engine.
- **What to do about it:** Plan obligations from the bootstrap numbers; use Monte Carlo for what-if exploration.
- **Trap:** It cannot invent a crisis that never happened in the sample, and it inherits the sample's survivorship.

### Block size (bootstrap)

*Glossary key: `block_bootstrap` · unit: days*

- **What it is:** Length of each contiguous historical window drawn (config bootstrap.block_size_days).
- **What it measures:** How much serial dependence is preserved.
- **How to read it for this portfolio:** 20 trading days keeps a month of momentum together; 1 day (iid) shuffles good and bad days apart and understates runs of bad news.
- **What to do about it:** Compare block 5 / 20 / 60: widening blocks usually widens the left tail.
- **Trap:** Larger blocks reduce the number of distinct combinations, so very large blocks make results lumpier.

### Markov regime engine

*Glossary key: `markov` · unit: text*

- **What it is:** Historical calendar-year portfolio returns are bucketed into 5 states by the configured thresholds; a 5x5 transition matrix is estimated from year-to-year moves; simulations draw state sequences and then a real return from the matching state.
- **What it measures:** A model of *regimes*: whether the portfolio is likely to spend the next years in bear or bull conditions.
- **How to read it for this portfolio:** It answers 'how likely is a bad stretch' better than it answers 'what is the terminal value'.
- **What to do about it:** Use bear_ever_prob and expected durations for the risk narrative; use MC/bootstrap for the money.
- **Trap:** Estimated from roughly 25 annual observations. Each transition probability has a wide confidence interval, and unobserved states are assumed to persist.

### Regime states and thresholds

*Glossary key: `markov_states` · unit: pct*

- **What it is:** severe_bear < -20%, bear -20% to -5%, neutral -5% to +5%, bull +5% to +20%, strong_bull > +20% of annual portfolio return (config markov.thresholds).
- **What it measures:** The definition of 'bad year' the whole regime model depends on.
- **How to read it for this portfolio:** A portfolio-level -5% year is already 'bear' because the thresholds apply to the whole portfolio, not to the S&P.
- **What to do about it:** Change the thresholds deliberately: they move state counts and therefore every Markov number.
- **Trap:** Thresholds are absolute, so a conservative bond-heavy portfolio may never leave 'neutral'.

### Transition matrix P

*Glossary key: `transition_matrix` · unit: ratio*

- **What it is:** P[i][j] = share of historical years in state i that were followed by a year in state j.
- **What it measures:** The probability of moving from one regime to another in one year.
- **How to read it for this portfolio:** A high diagonal means regimes persist - bad years come in runs.
- **What to do about it:** Read the diagonal for the current state; that persistence is what drives bear_ever_prob.
- **Trap:** Rows built from one or two observations are not probabilities, they are anecdotes; the engine marks unobserved rows as persistent.

### Stationary distribution

*Glossary key: `stationary_distribution` · unit: pct*

- **What it is:** Long-run share of years in each state implied by P (left eigenvector at 1).
- **What it measures:** The climate, as opposed to the weather: what the mix of regimes looks like over a long horizon.
- **How to read it for this portfolio:** If the stationary bear share is 25%, expect roughly one year in four to be a bear year over a long horizon.
- **What to do about it:** Use it to sanity-check the glide path's end equity target.
- **Trap:** It assumes the process is stable forever, which no market is.

### Expected regime duration

*Glossary key: `expected_duration` · unit: years*

- **What it is:** 1 / (1 - P[state][state]).
- **What it measures:** How long the portfolio is expected to stay in a regime once it is there.
- **How to read it for this portfolio:** A 2.5-year expected bear duration means a bad stretch is likely to span more than one planning year.
- **What to do about it:** If bear duration exceeds the years left before 2033, de-risking must happen before the bear arrives.
- **Trap:** Mean duration says nothing about the worst case; runs can be far longer.

### P(bear at any point 2027-2032)

*Glossary key: `bear_ever_prob` · unit: pct*

- **What it is:** Share of Markov simulations where at least one growth-phase year lands in bear or severe_bear.
- **What it measures:** The chance that the plan experiences at least one bad year before the split.
- **How to read it for this portfolio:** Usually high. It is a near-certainty statement, which is why it should not be used as an alarm by itself.
- **What to do about it:** Pair it with expected duration and terminal percentiles, not with the headline.
- **Trap:** 'At least one bear year' is a low bar; 60% here does not mean 60% chance of failure.

### P(bull by 2032)

*Glossary key: `bull_by_end_prob` · unit: pct*

- **What it is:** Share of Markov simulations whose final growth-phase year is bull or strong_bull.
- **What it measures:** The chance of arriving at the 2033 split in good conditions.
- **How to read it for this portfolio:** Arriving in a bull year is favourable for the split, but it says nothing about the path taken to get there.
- **What to do about it:** Do not use it as evidence that the reserve is safe.
- **Trap:** A bull final year is compatible with a -35% drawdown in 2029.

## 6. Risk measures (VaR and CVaR)

The most misread rows in the workbook. Read the horizon and the basis before comparing any two.

### VaR (value at risk)

*Glossary key: `var` · unit: pct*

- **What it is:** Historical: -quantile(returns, 1 - confidence). Parametric: -(mean + z x std). Monte Carlo: -quantile of simulated terminal return vs contributions.
- **What it measures:** The loss that is not exceeded in (1 - confidence) of periods - a threshold, not an average.
- **How to read it for this portfolio:** VaR 95% = 4% means 19 months in 20 lose less than 4%; it says nothing about how bad the 20th month is.
- **What to do about it:** Always read VaR together with CVaR, which measures the part VaR ignores.
- **Trap:** Sign convention: VaR is reported as a positive loss. A 'VaR 95% = 0.04' means a 4% loss, not a 4% gain; a NEGATIVE VaR means the 5th-percentile outcome is itself a gain. Historical, parametric and Monte Carlo VaR are computed on different horizons and bases - never compare them directly.

### CVaR / expected shortfall

*Glossary key: `cvar` · unit: pct*

- **What it is:** Negative of the mean of returns at or beyond the VaR quantile.
- **What it measures:** The average loss in the bad tail - what you actually lose when the bad case happens.
- **How to read it for this portfolio:** CVaR is the number that should size a reserve. If CVaR95 is 30%, the worst 5% of outcomes lose a third on average.
- **What to do about it:** The rule engine raises a HIGH tail flag above 30% terminal CVaR95.
- **Trap:** Terminal CVaR is measured on the 2033 outcome relative to contributions over six years, not on a month. It is a horizon loss, not a monthly one. A NEGATIVE CVaR is not an error: it means that even the worst 5% of simulated outcomes are, on average, still gains - the tail is not loss-making under these assumptions.

### Horizon warning (VaR rows)

*Glossary key: `var_horizon_warning` · unit: text*

- **What it is:** Risk-sheet VaR/CVaR rows are one-month horizon; comparison-table VaR/CVaR rows are 2033 terminal horizon.
- **What it measures:** The same label is used for two different measurements in this report.
- **How to read it for this portfolio:** A 4% monthly VaR and a 30% terminal VaR are consistent, not contradictory.
- **What to do about it:** Check the column header before comparing any two VaR numbers.
- **Trap:** This is the single most common misreading in the workbook.

## 7. Sensitivity and stress

Sensitivity asks 'how much can the assumptions be wrong'. Stress asks 'what happens in a named bad world'.

### Sensitivity grid

*Glossary key: `sensitivity_grid` · unit: pct*

- **What it is:** For each (return shift, volatility multiplier) pair, re-run the simulation and record median terminal, p5, success probability, reserve-funding probability, median drawdown, VaR/CVaR.
- **What it measures:** How much the answer depends on the assumptions, mapped as a surface instead of a single what-if.
- **How to read it for this portfolio:** Find the base cell (shift 0, multiplier 1.0), then walk outward. A plan whose success collapses one row away is fragile.
- **What to do about it:** Report the region where success stays above your standard, not just the base case.
- **Trap:** Return shifts are applied to every asset equally; it is a systematic shock, not a single-name change.

### Minimum return shift for 90% success

*Glossary key: `min_return_for_success` · unit: pct*

- **What it is:** Smallest return shift in the grid where success probability is still at or above 90%.
- **What it measures:** How much of your return assumption you can lose before the plan stops working.
- **How to read it for this portfolio:** -2% means the plan survives 2pp lower returns everywhere. A value near 0 means no margin at all.
- **What to do about it:** This is the number to quote when someone challenges your expected returns.
- **Trap:** It is found at the grid's coarse 1pp steps.

### Fragile volatility threshold

*Glossary key: `fragile_vol_threshold` · unit: ratio*

- **What it is:** At the base return assumption, the smallest volatility multiplier >= 1.0 where success falls below 75%.
- **What it measures:** How much extra volatility the plan can absorb.
- **How to read it for this portfolio:** 1.1 means a 10% increase in volatility breaks the plan; 1.5 means it is robust to a 50% volatility regime shift.
- **What to do about it:** Below 1.1 the engine raises a fragility flag.
- **Trap:** Volatility is scaled, not returns: it widens the distribution without changing the average.

### Sharpe proxy (sensitivity grid)

*Glossary key: `sharpe_proxy` · unit: ratio*

- **What it is:** Mean / standard deviation of the simulated annualised terminal outcomes in that grid cell.
- **What it measures:** A comparability score across grid cells, not a traded Sharpe ratio.
- **How to read it for this portfolio:** Use it to rank cells against each other; do not compare it with the historical Sharpe on the dashboard.
- **What to do about it:** Ignore its absolute level.
- **Trap:** It is computed on terminal outcomes over the whole horizon, so it is not annual return over annual volatility.

### Historical crisis replay

*Glossary key: `crisis_test` · unit: pct*

- **What it is:** Apply the actual daily returns of your holdings during a configured window (2008, 2020, 2022) to current weights and report portfolio return, worst holding, sector contributions and benchmark comparison.
- **What it measures:** What today's allocation would have done in a named past crisis.
- **How to read it for this portfolio:** The most persuasive evidence in the report because it uses no assumptions at all - only what happened.
- **What to do about it:** Compare against the 60/40 benchmark row to see whether the allocation added or subtracted protection.
- **Trap:** It is a static snapshot: no rebalancing, no glide path, no contributions during the window. Holdings that did not exist then are excluded.

### Hypothetical scenario shocks

*Glossary key: `hypothetical_shock` · unit: pct*

- **What it is:** Apply configured asset-class/sector shocks (severe equity crash, stagflation, recession, inflation shock) to current weights.
- **What it measures:** A named, assumption-driven stress: 'what if this kind of world happens'.
- **How to read it for this portfolio:** Use it to test whether the defensive sleeve actually defends. A stagflation scenario that loses 25% means it does not.
- **What to do about it:** Edit the shocks in config to match the scenario you are arguing about; the numbers follow immediately.
- **Trap:** Shocks are applied once, instantaneously, to today's weights. There is no recovery and no management response.

## 8. Stops and optimisation

Both are diagnostics. Neither is a mandate.

### Stop-loss backtest

*Glossary key: `stop_loss_backtest` · unit: pct*

- **What it is:** For each holding: hold, exit at the close that breaches a hard (vs entry) or trailing (vs running peak) stop, re-enter after 21 trading days; compare CAGR, volatility, Sharpe, Sortino, max drawdown, exits, turnover and missed upside against buy-and-hold.
- **What it measures:** Whether a stop would historically have improved the risk profile of that holding.
- **How to read it for this portfolio:** A stop that cuts max drawdown a lot while giving up little CAGR is worth considering. One that cuts CAGR materially is a drag.
- **What to do about it:** Read 'missed upside' next to 'max drawdown' - that trade is the whole decision.
- **Trap:** Historical backtest on adjusted prices with a fixed 21-day re-entry. It is not advice, and it ignores taxes, slippage and the behavioural value of a stop.

### Missed upside (stop backtest)

*Glossary key: `missed_upside` · unit: pct*

- **What it is:** Sum of buy-and-hold returns minus sum of stopped-path returns over the same period.
- **What it measures:** The return given up by being out of the market after a stop.
- **How to read it for this portfolio:** Positive means the stop cost you return; negative means the stop helped.
- **What to do about it:** Compare it with the drawdown reduction to decide.
- **Trap:** It is a cumulative arithmetic difference, not an annualised figure.

### Suggested allocation (max-Sharpe diagnostic)

*Glossary key: `suggested_allocation` · unit: pct*

- **What it is:** SLSQP optimisation of expected return / volatility subject to weights summing to 1, per-position cap, cash floor and correlated-group caps.
- **What it measures:** The allocation the model's own assumptions consider most efficient.
- **How to read it for this portfolio:** Read the *differences* column, not the levels: it shows which positions the assumptions want bigger or smaller.
- **What to do about it:** Adopt selectively. It is a diagnostic, not a mandate.
- **Trap:** Optimisers amplify estimation error: a suggested weight is only as good as the expected-return input, and small input changes can move weights a lot.

## 9. Suggestions: how the rule flags work

Every recommendation in this project is a deterministic threshold breach with a traceable number, rule and action. No AI is involved.

### Rule flag

*Glossary key: `rule_flag` · unit: text*

- **What it is:** Deterministic comparison of a calculated value against a configured threshold. Each flag carries id, severity, metric, current value, threshold, rule text, action and evidence.
- **What it measures:** The suggestions in this report are rules, not opinions: every one can be traced to a number and a config key.
- **How to read it for this portfolio:** Severity ladder: CRITICAL > HIGH > WARNING > MONITOR > INFO. HIGH means the number breaches a planning standard; MONITOR means watch it; INFO is context.
- **What to do about it:** Work the flags in order; each action line is the specific response the rule was written to produce.
- **Trap:** A flag is a threshold breach, not a forecast. No AI or judgement is involved, and no flag fires without a configured rule.

### Severity ladder

*Glossary key: `severity_levels` · unit: text*

- **What it is:** CRITICAL, HIGH, WARNING, MONITOR, INFO (rules/rule_engine.py SEVERITY_ORDER).
- **What it measures:** How much attention a finding deserves.
- **How to read it for this portfolio:** HIGH = a configured planning standard is breached (position cap, reserve funding, tail loss, model disagreement). WARNING = a band or limit is out of tolerance. MONITOR = a data or governance weakness. INFO = context.
- **What to do about it:** Fix HIGH before optimising anything at MONITOR.
- **Trap:** Severity is about the rule, not about the size of the loss.

## 10. Data quality and what the model refuses to invent

These rows are the model telling you where its own numbers are weak.

### Estimate confidence (High / Medium / Low)

*Glossary key: `confidence` · unit: text*

- **What it is:** High if >=10 years of monthly history, Medium if >=2, Low otherwise.
- **What it measures:** How much the holding's return, volatility and correlation estimates can be trusted.
- **How to read it for this portfolio:** A Low-confidence holding contributes numbers that look precise but are not. Its simulation weight is built on a guess.
- **What to do about it:** For Low-confidence names, prefer the spreadsheet's own expected return/volatility, or widen the sensitivity range.
- **Trap:** History length is not the same as stability: 25 years of a regime that has since ended is still misleading.

### Data provenance (source / as-of)

*Glossary key: `data_provenance` · unit: text*

- **What it is:** Per ticker: cache hit, network download, or committed bundled snapshot, with rows, inception date and data-as-of date.
- **What it measures:** Where each price series came from and how current it is.
- **How to read it for this portfolio:** Two runs with different provenance can differ. 'bundled snapshot' means the analysis used the committed offline dataset, not live prices.
- **What to do about it:** Refresh with `python scripts/build_offline_dataset.py` when you need current prices, or run with --offline for a reproducible result.
- **Trap:** Offline reproducibility and live freshness are different goals; the report states which one it used.

### Return basis (adjusted close)

*Glossary key: `adjusted_close_basis` · unit: text*

- **What it is:** All prices are dividend- and split-adjusted closes, i.e. total-return series.
- **What it measures:** Returns include reinvested dividends, not just price change.
- **How to read it for this portfolio:** For bond ETFs and dividend payers this materially raises measured return versus raw price.
- **What to do about it:** Compare only against total-return benchmarks (this report's SPY/AGG series are total return).
- **Trap:** Comparing these results to a price-index chart will make the model look too optimistic.

### Survivorship bias

*Glossary key: `survivorship_bias` · unit: text*

- **What it is:** Historical series only contain securities that still exist.
- **What it measures:** Failures are structurally missing from the data the estimates come from.
- **How to read it for this portfolio:** Every historical return figure here is mildly flattering.
- **What to do about it:** Do not conclude 'this name has never gone to zero' from a history that cannot show it.
- **Trap:** It cannot be corrected by the model; it can only be acknowledged.

### P&L basis

*Glossary key: `pl_note` · unit: text*

- **What it is:** Dollar P&L is computed only when cost basis is supplied; otherwise return-based attribution is used.
- **What it measures:** Whether the report is talking about accounting profit or investment performance.
- **How to read it for this portfolio:** Without cost basis there are no dollar gains and losses in the report, only percentage returns.
- **What to do about it:** Add a cost basis column if you need tax or realised-gain framing.
- **Trap:** The model never invents a cost basis. Missing data is reported as missing.

### Taxes

*Glossary key: `tax_note` · unit: text*

- **What it is:** Excluded unless tax-lot information is supplied.
- **What it measures:** All figures are pre-tax.
- **How to read it for this portfolio:** Rebalancing suggestions ignore tax cost, so a 'trim the winner' recommendation is more expensive in reality than in the model.
- **What to do about it:** Stage trims across years, as the position-cap action text suggests.
- **Trap:** Transaction cost is modelled (0.1% of turnover); tax is not modelled at all.

## 11. Rule caps and thresholds (what the flags compare against)

Every rule flag is a measured value against a cap you configured. These are those caps, and what breaching one actually means.

### Position weight cap

*Glossary key: `max_position_weight` · unit: pct*

- **What it is:** risk.max_position_weight in the config, compared against each holding's weight.
- **What it measures:** The largest single-name exposure the plan is allowed to carry.
- **How to read it for this portfolio:** A breach says one company, not one sector, can move the whole plan. The severity follows how far past the cap it sits.
- **What to do about it:** Trim toward the cap in stages rather than in one trade, so the exit does not become the risk.
- **Trap:** Passing the cap test says nothing about correlated groups: several legal positions can be one economic bet.

### Sector weight cap

*Glossary key: `max_sector_weight` · unit: pct*

- **What it is:** risk.max_sector_weight in the config, compared against each sector total.
- **What it measures:** How much of the plan may sit in one sector.
- **How to read it for this portfolio:** Sector caps catch concentration that position caps miss, because it aggregates several compliant holdings.
- **What to do about it:** Reduce the sector total, not just the biggest name in it.
- **Trap:** Sector labels come from a lookup table; an unmapped ticker lands in a catch-all sector and can hide real concentration.

### Correlated group cap

*Glossary key: `max_correlated_group_weight` · unit: pct*

- **What it is:** risk.max_correlated_group_weight in the config, compared against the total weight of holdings whose correlation exceeds risk.correlation_threshold.
- **What it measures:** The size of the single bet that several correlated holdings actually represent.
- **How to read it for this portfolio:** This is the cap that tells the truth about diversification. A portfolio can pass every position and sector cap and still breach this one.
- **What to do about it:** Trim the group as a unit toward the cap.
- **Trap:** Correlation is estimated on shared history, so a cluster can be understated when a holding has a short record.

### Cash floor

*Glossary key: `min_cash_weight` · unit: pct*

- **What it is:** risk.min_cash_weight in the config, compared against the cash-like weight.
- **What it measures:** The minimum buffer the plan keeps outside market exposure.
- **How to read it for this portfolio:** Below the floor, the first payment or the first drawdown has to be funded by selling something at whatever price is available.
- **What to do about it:** Restore the floor from the next contribution rather than by selling into a fall.
- **Trap:** Cash-like means excluded from simulation, so its return is zero in every scenario - it buys safety, not yield.

### Rebalancing band

*Glossary key: `rebalance_band` · unit: pct*

- **What it is:** Absolute: target +/- band percentage points. Relative: target x (1 +/- relative_band).
- **What it measures:** How far a class may drift before the model forces a trade.
- **How to read it for this portfolio:** Tight bands mean more trades and more transaction cost; loose bands mean the glide path is advisory only.
- **What to do about it:** Check mean_turnover and mean_rebalances to see what the band actually costs.
- **Trap:** Bands are tested on asset *class* weights at month end, not on individual holdings.

### Engine disagreement spread

*Glossary key: `engine_disagreement` · unit: pct*

- **What it is:** Relative difference between the Monte Carlo and historical bootstrap values of the same metric.
- **What it measures:** How much the answer depends on which model you believe.
- **How to read it for this portfolio:** A large spread is a finding, not noise: it means the assumption set, not the holdings, is driving the answer.
- **What to do about it:** Report ranges rather than point estimates, and decide on the more conservative engine.
- **Trap:** The engines answer different questions, so some spread is expected. Only a spread in a decision-relevant metric matters.

### Thesis coverage

*Glossary key: `thesis_coverage` · unit: count*

- **What it is:** Number of holdings with no stated investment thesis in the input.
- **What it measures:** How much of the portfolio has no written reason for being there.
- **How to read it for this portfolio:** A missing thesis is not a risk estimate, it is a governance gap: it means nobody wrote down why the position should exist.
- **What to do about it:** Write the thesis in the input's thesis column, or remove the position.
- **Trap:** The model cannot judge whether a thesis is good, only whether one is recorded.

### Rule flag

*Glossary key: `rule_flag` · unit: text*

- **What it is:** Deterministic comparison of a calculated value against a configured threshold. Each flag carries id, severity, metric, current value, threshold, rule text, action and evidence.
- **What it measures:** The suggestions in this report are rules, not opinions: every one can be traced to a number and a config key.
- **How to read it for this portfolio:** Severity ladder: CRITICAL > HIGH > WARNING > MONITOR > INFO. HIGH means the number breaches a planning standard; MONITOR means watch it; INFO is context.
- **What to do about it:** Work the flags in order; each action line is the specific response the rule was written to produce.
- **Trap:** A flag is a threshold breach, not a forecast. No AI or judgement is involved, and no flag fires without a configured rule.

### Severity ladder

*Glossary key: `severity_levels` · unit: text*

- **What it is:** CRITICAL, HIGH, WARNING, MONITOR, INFO (rules/rule_engine.py SEVERITY_ORDER).
- **What it measures:** How much attention a finding deserves.
- **How to read it for this portfolio:** HIGH = a configured planning standard is breached (position cap, reserve funding, tail loss, model disagreement). WARNING = a band or limit is out of tolerance. MONITOR = a data or governance weakness. INFO = context.
- **What to do about it:** Fix HIGH before optimising anything at MONITOR.
- **Trap:** Severity is about the rule, not about the size of the loss.

## 12. Scorecard

A triage summary, deliberately not the conclusion.

### Scorecard / overall score

*Glossary key: `scorecard` · unit: score*

- **What it is:** Category scores (0-10) for funding, concentration, diversification, data quality and process, combined into an overall score.
- **What it measures:** A one-number summary of plan quality, meant for triage rather than decision-making.
- **How to read it for this portfolio:** Use it to find which category to open first. It is deliberately not the conclusion of the report.
- **What to do about it:** A high score with HIGH rule flags means the scorecard is measuring structure, not outcome.
- **Trap:** It is a weighted judgement encoded in code; changing weights changes the score, not the portfolio.

## The ten most common misreadings

1. **Quoting the median as if it were a promise.** The median is the middle outcome: half the simulations land worse. Size obligations from p5-p10.
2. **Reading nominal success as purchasing-power success.** `prob_terminal_gt_start` counts a year of 2% inflation and 1% return as success. `prob_terminal_gt_real_start` does not.
3. **Comparing VaR numbers across sheets.** Risk-sheet VaR is one-month; comparison-table VaR is the 2033 terminal outcome. Different horizons, different bases.
4. **Treating a high `bear_ever_prob` as a warning.** It means 'at least one bear year before 2033', which is close to a certainty for an equity-heavy plan.
5. **Believing the Gaussian Monte Carlo.** Gaussian MC understates crash frequency. The bootstrap engine is the one that has actually seen 2008.
6. **Reading a 7-holding portfolio as diversified.** Compare holding count with `effective_n`. Seven names can be three bets.
7. **Confusing the suggested allocation with a target.** It is a max-Sharpe diagnostic built on your own expected-return inputs; it amplifies estimation error.
8. **Assuming a stop-loss backtest proves stops work.** It compares one fixed policy with a fixed 21-day re-entry on one history. Read `missed_upside` first.
9. **Assuming the run used live prices.** Check the Data provenance rows. An offline run uses the committed snapshots in `data/offline/`.
10. **Assuming the report includes taxes.** It does not. Transaction cost is modelled; tax is not.

## Where to look in the workbook

The generated workbook opens on a **Read Me** sheet rendered from the same source as this list.

| Question | Where to look |
|---|---|
| Can the 2033 obligation actually be funded? | Model Comparison, Risk, Executive Summary |
| How bad can it get? | Monte Carlo, Historical Bootstrap, Risk |
| Is this actually diversified? | Correlation Matrix, Risk (cluster table), Holdings |
| Which decisions dominate the outcome? | Rule Flags, Scorecard |
| How much do my assumptions matter? | Sensitivity |
| What would a real crisis do to this mix? | Stress Tests |
| What the model could not verify | Data Quality |
| What does any given number mean? | Definitions |

| Sheet | What it is for |
|---|---|
| `Executive Summary` | The headline numbers and the verdict, in one screen. |
| `Holdings` | Every position: weight, sector, expected return, volatility, beta, cluster, confidence and thesis. |
| `Sector Allocation` | Sector totals versus the configured targets, with the gap for each sector. |
| `Correlation Matrix` | Pairwise monthly correlation between holdings. Look for blocks. |
| `Historical Performance` | What the current weights would have done over the price history, with benchmarks. |
| `Monte Carlo` | Parametric simulation results: percentiles, probabilities, VaR/CVaR on the 2033 outcome. |
| `Markov Model` | Regime model: transition matrix, state probabilities by year, bear-market exposure. |
| `Historical Bootstrap` | Resampling of real historical sequences: the reality check on the parametric model. |
| `Model Comparison` | All three engines side by side. Where they disagree is where the planning risk lives. |
| `Sensitivity` | The assumption grid: which assumption actually moves the answer. |
| `Risk` | Risk metrics, drawdown recovery events, and the correlated-cluster table. |
| `Stress Tests` | Crisis replays on the current mix, plus hypothetical forward scenarios. |
| `Glide Path` | The de-risking schedule and what each variant does to the funding probabilities. |
| `Rebalancing` | Current weight, target, bands and the suggested trade for each holding. |
| `Rule Flags` | Every triggered rule: metric, current value, threshold, action and severity. |
| `Investment Theses` | The stated thesis per holding, and which holdings have none. |
| `Data Quality` | What the model could not verify: missing data, skipped windows, low-confidence series. |
| `Scorecard` | Each configured test against its threshold, with the pass/fail result. |
| `Stop-Loss Backtests` | Historical stop backtests. Risk discipline evidence, not trading advice. |
| `Definitions` | Every metric in this workbook: what it is, how to read it, what to do, and the trap. |
| `Worked Examples` | The arithmetic behind each headline metric, recalculated with this portfolio's own numbers. |

| Severity | What it means |
|---|---|
| **CRITICAL** | The plan fails under the configured rules. Address before relying on any other number. |
| **HIGH** | A rule is breached in a way that changes the answer. Act on it. |
| **WARNING** | Outside the configured comfort zone. Review and decide. |
| **MONITOR** | Inside the rules but worth watching over time. |
| **INFO** | Context, not a problem. |

## Reading the charts

One entry per figure in the web dashboard, generated from the same file as the captions the dashboard itself renders.

### Current allocation by holding

- **What it shows:** Each holding's share of invested capital, from the weights the input actually supplied.
- **How to read it:** A slice is a position, not a bet. Two slices in the same correlated cluster are one bet wearing two names.
- **Watch out:** If the weights came from market value rather than an explicit target column, this is a snapshot, not a policy.
- **Metrics behind it:** `weights_source`, `hhi`, `effective_n`

### Allocation by sector versus configured targets

- **What it shows:** Sector totals against the target weights in the config, with the gap for each sector.
- **How to read it:** The gap is the rebalancing distance. A large gap in a defensive sector usually means growth drifted up, not that anything broke.
- **Watch out:** Sector labels are assigned by a lookup table; an unmapped ticker lands in a catch-all sector and can hide real concentration.
- **Metrics behind it:** `correlation_cluster`, `hhi`, `suggested_allocation`

### Historical cumulative growth

- **What it shows:** Growth of one unit of capital in the portfolio and its benchmarks over the available history.
- **How to read it:** This is what already happened, on the current mix. It is the calibration evidence for the simulations, not a forecast.
- **Watch out:** The window is as long as the shortest holding's history, so a young ticker shortens the whole comparison.
- **Metrics behind it:** `cagr_historical`, `max_drawdown`, `survivorship_bias`

### Historical drawdown

- **What it shows:** Distance below the running peak, month by month.
- **How to read it:** Depth, duration and the time to recover are three different risks. A shallow drawdown that never fully recovers is worse than a deep one that does.
- **Watch out:** Drawdown is measured on the portfolio you hold today; a rebalance changes the answer completely.
- **Metrics behind it:** `drawdown_peak_trough_recovery`, `recovery_days`, `max_drawdown`

### Asset correlation matrix (monthly)

- **What it shows:** Pairwise monthly correlation between holdings.
- **How to read it:** Look for blocks of high values. A block is one exposure expressed several ways.
- **Watch out:** Correlations are estimated on the shared history. Two tickers with little overlap produce a weak estimate that looks reassuringly low.
- **Metrics behind it:** `correlation`, `correlation_cluster`, `effective_n`, `confidence`

### Sector correlation matrix (monthly)

- **What it shows:** Correlation between sector aggregates rather than individual holdings.
- **How to read it:** Use this to judge whether the sector labels are doing any work. If two 'different' sectors move as one, the diversification is cosmetic.
- **Watch out:** Aggregating hides the position-level concentration that the holdings view shows.
- **Metrics behind it:** `correlation`, `correlation_cluster`

### Terminal value distributions (all engines overlaid)

- **What it shows:** The distribution of the 2033 outcome under each simulation engine.
- **How to read it:** Compare the left tails first. Where the engines disagree about the bad tail is where the planning risk lives.
- **Watch out:** Different engines answer different questions; a wider distribution is not automatically a worse portfolio.
- **Metrics behind it:** `terminal_2033`, `terminal_percentiles`, `median_terminal`, `bootstrap`

### Monte Carlo fan chart

- **What it shows:** Percentile bands of simulated portfolio value from now to the glide end.
- **How to read it:** The bands are percentiles of many simulated paths, not a confidence interval around a forecast of the mean.
- **Watch out:** The bands widen with time by construction. Width at the far end says more about horizon than about the holdings.
- **Metrics behind it:** `monte_carlo`, `terminal_percentiles`, `var_horizon_warning`

### Historical bootstrap fan chart

- **What it shows:** The same fan built by resampling blocks of real historical returns.
- **How to read it:** Every path here is a sequence that actually happened somewhere in the data. It is the reality check on the parametric model.
- **Watch out:** It cannot invent a crisis that is not in the sample, so it understates novel shocks.
- **Metrics behind it:** `bootstrap`, `block_bootstrap`, `terminal_percentiles`

### Engine comparison

- **What it shows:** Median outcome, tail percentiles, VaR/CVaR and reserve-funding probability for all three engines.
- **How to read it:** Plan against the most conservative engine that is credible for the decision, not against the average of the three.
- **Watch out:** A large spread between engines is a finding in itself: it means the answer depends on assumptions, not on the holdings.
- **Metrics behind it:** `median_terminal`, `prob_all_payments_funded`, `var`, `cvar`

### Sensitivity: probability of success

- **What it shows:** Probability of meeting the obligation across a grid of return and volatility assumptions.
- **How to read it:** Find the contour where success drops below the level you need, then ask how far the current assumptions sit from it.
- **Watch out:** The grid is a map of assumptions, not probabilities. The cells are not equally likely.
- **Metrics behind it:** `sensitivity_grid`, `fragile_vol_threshold`, `min_return_for_success`

### Sensitivity: median 2033 terminal value

- **What it shows:** Median terminal value across the same assumption grid.
- **How to read it:** Read the slope, not the level: steep colour changes mark the assumption that actually moves the answer.
- **Watch out:** Median value can look safe while the probability of success collapses in the same region.
- **Metrics behind it:** `sensitivity_grid`, `fragile_vol_threshold`

### Crisis replay

- **What it shows:** How the current mix would have behaved in each configured historical crisis window.
- **How to read it:** This is the mix, not the history: it answers 'what would this portfolio have done', holding weights fixed.
- **Watch out:** Windows with no overlapping price history are reported as skipped rather than scored as zero.
- **Metrics behind it:** `crisis_test`, `max_drawdown_growth`, `recovery_days`

### Glide path

- **What it shows:** The configured de-risking schedule from the start equity weight to the end weight.
- **How to read it:** The glide path is a decision you made, shown as a schedule. The simulations follow it mechanically.
- **Watch out:** Changing the method changes the schedule and therefore every downstream probability; it is not a cosmetic setting.
- **Metrics behind it:** `glide_path`, `contributions`

### Position concentration versus the limit

- **What it shows:** Each holding's weight against the configured maximum position weight.
- **How to read it:** Bars past the limit line are the positions the rule engine flags. Their severity follows the size of the breach.
- **Watch out:** A portfolio can pass every position limit and still be concentrated, because correlated clusters add up.
- **Metrics behind it:** `hhi`, `effective_n`, `top3_top5_top10`, `rebalance_band`

### Portfolio scorecard

- **What it shows:** Each configured test, its threshold, the current value and the pass/fail result.
- **How to read it:** Every bar is a rule with a stated threshold. Nothing here is a judgement call or a model opinion.
- **Watch out:** A pass means 'inside the threshold you configured', not 'safe'.
- **Metrics behind it:** `scorecard`, `rule_flag`, `severity_levels`

### Markov transition matrix

- **What it shows:** Estimated probability of moving from each market state to each other state in one year.
- **How to read it:** Each row sums to one: it is the chance of leaving a state, not the chance of staying popular.
- **Watch out:** Estimates inherit the sample. A state that rarely occurs in the data has a poorly estimated row.
- **Metrics behind it:** `transition_matrix`, `markov`

### Markov state distribution by year

- **What it shows:** Modelled probability of the market being in each state in each year to the glide end.
- **How to read it:** This is regime risk over time: how the chance of a bear market is expected to build or fade.
- **Watch out:** The model is stationary, so it cannot represent a one-off structural change.
- **Metrics behind it:** `markov_states`, `stationary_distribution`, `bear_ever_prob`

### Return contribution by holding

- **What it shows:** Each holding's contribution to portfolio return over the trailing window.
- **How to read it:** Contribution combines weight and performance. A small position can be the reason the portfolio worked.
- **Watch out:** Contribution is backward-looking and weight-dependent; it is not a forecast of what will drive results.
- **Metrics behind it:** `contributions`, `turnover`, `pl_note`

### Maximum drawdown distribution

- **What it shows:** Distribution of the worst simulated peak-to-trough decline before the glide end.
- **How to read it:** Read the right tail: it is how deep the worst realistic path gets, which is what determines whether the plan survives.
- **Watch out:** This is simulated drawdown on terminal paths, not the historical drawdown chart above.
- **Metrics behind it:** `max_drawdown`, `prob_capital_depletion`, `var_horizon_warning`

## Metric reference table

| Key | Label | Unit | One-line meaning |
|---|---|---|---|
| `adjusted_close_basis` | Return basis (adjusted close) | text | Returns include reinvested dividends, not just price change. |
| `annual_volatility` | Volatility (historical, annual) | pct | Size of typical month-to-month swings in the current-weight portfolio. |
| `bear_ever_prob` | P(bear at any point 2027-2032) | pct | The chance that the plan experiences at least one bad year before the split. |
| `block_bootstrap` | Block size (bootstrap) | days | How much serial dependence is preserved. |
| `bootstrap` | Historical bootstrap engine | text | What the plan would have done if the future repeated stretches of the actual past, including 2008 and 2020. |
| `bull_by_end_prob` | P(bull by 2032) | pct | The chance of arriving at the 2033 split in good conditions. |
| `cagr_historical` | Historical CAGR | pct | The single compound growth rate that would have reproduced the past exactly. |
| `cagr_money_weighted` | Expected CAGR (Monte Carlo) | pct | The annual growth rate implied by the median outcome against the money put in. |
| `confidence` | Estimate confidence (High / Medium / Low) | text | How much the holding's return, volatility and correlation estimates can be trusted. |
| `contributions` | Invested capital / contributions | money | The money the simulation starts compounding, and the reference point for every success probability. |
| `correlation` | Correlation (pairwise, monthly) | ratio | Whether two holdings move together, which is what decides if they are really two bets or one. |
| `correlation_cluster` | Correlation cluster | text | The set of holdings that behave like one bet. |
| `crisis_test` | Historical crisis replay | pct | What today's allocation would have done in a named past crisis. |
| `cvar` | CVaR / expected shortfall | pct | The average loss in the bad tail - what you actually lose when the bad case happens. |
| `data_provenance` | Data provenance (source / as-of) | text | Where each price series came from and how current it is. |
| `downside_deviation` | Downside deviation | pct | How violent the losing months are. |
| `drawdown_peak_trough_recovery` | Drawdown peak / trough / recovery dates | text | The shape of the worst episode: how fast it fell and how long you waited. |
| `effective_n` | Effective number of independent bets | count | How many truly separate bets the weighting is equivalent to. |
| `engine_disagreement` | Engine disagreement spread | pct | How much the answer depends on which model you believe. |
| `expected_duration` | Expected regime duration | years | How long the portfolio is expected to stay in a regime once it is there. |
| `expected_return` | Expected return (annual) | pct | The central return assumption driving every simulation. |
| `facility_contribution` | Facility contribution | money | What is left for the facility after the reserve obligation is met. |
| `fragile_vol_threshold` | Fragile volatility threshold | ratio | How much extra volatility the plan can absorb. |
| `glide_path` | Glide path targets | pct | The planned de-risking schedule into the payment phase. |
| `hhi` | HHI (concentration index) | pct | How much of the portfolio sits in a few positions. |
| `hypothetical_shock` | Hypothetical scenario shocks | pct | A named, assumption-driven stress: 'what if this kind of world happens'. |
| `inflation_base` | Inflation assumption | pct | The price-level assumption behind every 'real' or 'above floor' probability. |
| `markov` | Markov regime engine | text | A model of *regimes*: whether the portfolio is likely to spend the next years in bear or bull conditions. |
| `markov_states` | Regime states and thresholds | pct | The definition of 'bad year' the whole regime model depends on. |
| `max_correlated_group_weight` | Correlated group cap | pct | The size of the single bet that several correlated holdings actually represent. |
| `max_drawdown` | Max drawdown (historical) | pct | The deepest peak-to-trough fall actually experienced. |
| `max_drawdown_growth` | Max drawdown (growth phase) | pct | How painful the ride to 2033 is likely to be. |
| `max_position_weight` | Position weight cap | pct | The largest single-name exposure the plan is allowed to carry. |
| `max_sector_weight` | Sector weight cap | pct | How much of the plan may sit in one sector. |
| `mean_annual_return` | Mean annual return (historical) | pct | The average month, annualised by compounding. |
| `median_terminal` | Median terminal value | money | The middle outcome: half the simulations land below it. |
| `min_cash_weight` | Cash floor | pct | The minimum buffer the plan keeps outside market exposure. |
| `min_return_for_success` | Minimum return shift for 90% success | pct | How much of your return assumption you can lose before the plan stops working. |
| `missed_upside` | Missed upside (stop backtest) | pct | The return given up by being out of the market after a stop. |
| `monte_carlo` | Monte Carlo engine | text | What the plan does under a clean statistical model of the assumptions. |
| `pl_note` | P&L basis | text | Whether the report is talking about accounting profit or investment performance. |
| `prob_all_payments_funded` | Probability all reserve payments funded | pct | Whether the obligation is actually met on time, every time. |
| `prob_capital_depletion` | Probability of capital depletion | pct | Total-loss probability under the model's assumptions. |
| `prob_facility_negative` | Probability the facility gets nothing | pct | How often the plan covers the obligation but has nothing left over. |
| `prob_floor_100 / 90 / 80 / 70` | Capital-floor probabilities | pct | How likely the plan is to preserve at least a given fraction of real purchasing power. |
| `prob_terminal_gt_real_start` | Success above real capital | pct | Did the portfolio beat inflation as well as the contributions? |
| `prob_terminal_gt_start` | Success: terminal > contributions | pct | The plain 'did the money grow' probability. |
| `rebalance_band` | Rebalancing band | pct | How far a class may drift before the model forces a trade. |
| `recovery_days` | Days to recover (drawdown events) | days | How long a drawdown kept you below your previous high. |
| `required_reserve` | Required reserve (present value) | money | The lump sum needed today to fund the scheduled payments, assuming the reserve keeps earning the discount rate. |
| `risk_free_rate` | Risk-free rate | pct | The floor return and the discount rate reference for Sharpe-style ratios. |
| `rule_flag` | Rule flag | text | The suggestions in this report are rules, not opinions: every one can be traced to a number and a config key. |
| `scorecard` | Scorecard / overall score | score | A one-number summary of plan quality, meant for triage rather than decision-making. |
| `sensitivity_grid` | Sensitivity grid | pct | How much the answer depends on the assumptions, mapped as a surface instead of a single what-if. |
| `severity_levels` | Severity ladder | text | How much attention a finding deserves. |
| `sharpe` | Sharpe (historical) | ratio | Return earned per unit of swing taken. |
| `sharpe_proxy` | Sharpe proxy (sensitivity grid) | ratio | A comparability score across grid cells, not a traded Sharpe ratio. |
| `sortino` | Sortino (historical) | ratio | Return per unit of *bad* movement; upside is not penalised. |
| `split_month` | 2033 split | money | The moment the portfolio is cut into the obligation and the surplus. |
| `stationary_distribution` | Stationary distribution | pct | The climate, as opposed to the weather: what the mix of regimes looks like over a long horizon. |
| `stop_loss_backtest` | Stop-loss backtest | pct | Whether a stop would historically have improved the risk profile of that holding. |
| `student_t` | Student-t simulation | text | The same assumptions with fatter tails. |
| `suggested_allocation` | Suggested allocation (max-Sharpe diagnostic) | pct | The allocation the model's own assumptions consider most efficient. |
| `survivorship_bias` | Survivorship bias | text | Failures are structurally missing from the data the estimates come from. |
| `tax_note` | Taxes | text | All figures are pre-tax. |
| `terminal_2033` | Terminal value (2033) | money | The outcome the whole plan is judged on. |
| `terminal_percentiles` | Terminal percentiles (p5 ... p95) | money | The full range of plausible outcomes. |
| `thesis_coverage` | Thesis coverage | count | How much of the portfolio has no written reason for being there. |
| `top3_top5_top10` | Top 3 / 5 / 10 weight | pct | How much of the portfolio the biggest names control. |
| `transition_matrix` | Transition matrix P | ratio | The probability of moving from one regime to another in one year. |
| `turnover` | Turnover / rebalances (mean) | money | How much trading the policy actually requires. |
| `v2031 / projected_facility_2031` | 2031 sponsor checkpoint | money | An early warning read: how the plan looks two years before the split. |
| `var` | VaR (value at risk) | pct | The loss that is not exceeded in (1 - confidence) of periods - a threshold, not an average. |
| `var_horizon_warning` | Horizon warning (VaR rows) | text | The same label is used for two different measurements in this report. |
| `volatility` | Volatility (annual) | pct | How widely a holding's monthly returns scatter around their average. |
| `weights_source` | Weights source | text | Tells you the origin of the allocation the whole model is built on. |

_76 metric definitions. Add a key to `src/metric_glossary.py` and re-run the generator to extend every view at once._
