"""Explicit cash-flow schedule, validated against the competition case rules.

Source of the rules: 2026 Wharton Global Youth "Gao Case Study" (Investment Competition Guide).
Every projection in the model is driven by the schedule built here, so the only money that
moves is money the case says moves:

  * Year number = calendar year - year_zero (2026 is Year 0, 2027 Year 1, 2033 Year 7).
  * All contributions and withdrawals occur at the *beginning* of the year.
  * Contributions: $300,000 (2027) and $150,000 (2028). No other adds or withdrawals before 2033.
  * 2033: before the first operating payment, the operating reserve is set aside; the rest is
    available for the facility contribution.
  * Ten operating payments of a fixed (not inflation-adjusted) $50,000, one per year, 2033-2042.
  * Gains/losses from the WInS trading period are never part of the projection.
  * No personal income tax / capital-gains tax.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MONTHS_PER_YEAR = 12


class CashflowError(ValueError):
    """The configured cash flows are malformed or contradict the case rules."""


@dataclass(frozen=True)
class CashflowEvent:
    year: int
    amount: float          # positive, always; direction is given by `kind`
    kind: str              # "contribution" | "withdrawal" | "operating_payment"

    def year_number(self, year_zero: int) -> int:
        return self.year - year_zero


@dataclass
class CashflowSchedule:
    year_zero: int
    start_year: int                    # first simulated year (first cash arrives here)
    reserve_setup_year: int            # year the operating reserve is carved out
    checkpoint_year: int               # year the co-sponsor range is communicated
    contributions: list[CashflowEvent] = field(default_factory=list)
    withdrawals: list[CashflowEvent] = field(default_factory=list)
    payments: list[CashflowEvent] = field(default_factory=list)

    # ---- derived views the simulator consumes -------------------------------------------
    def month_of(self, year: int) -> int:
        """Month index of January of `year` (all flows happen at the start of the year)."""
        return (year - self.start_year) * MONTHS_PER_YEAR

    @property
    def contribution_months(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for e in self.contributions:
            out[self.month_of(e.year)] = out.get(self.month_of(e.year), 0.0) + e.amount
        return out

    @property
    def withdrawal_months(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for e in self.withdrawals:
            out[self.month_of(e.year)] = out.get(self.month_of(e.year), 0.0) + e.amount
        return out

    @property
    def payment_months(self) -> list[int]:
        return [self.month_of(e.year) for e in self.payments]

    @property
    def payment_amount(self) -> float:
        return self.payments[0].amount if self.payments else 0.0

    @property
    def first_payment_year(self) -> int:
        return self.payments[0].year

    @property
    def last_payment_year(self) -> int:
        return self.payments[-1].year

    @property
    def total_contributions(self) -> float:
        return float(sum(e.amount for e in self.contributions))

    @property
    def total_withdrawals(self) -> float:
        return float(sum(e.amount for e in self.withdrawals))

    @property
    def net_invested(self) -> float:
        """Contributions minus pre-reserve withdrawals: the capital base returns are measured on."""
        return self.total_contributions - self.total_withdrawals

    def describe(self) -> list[str]:
        """Human-readable restatement of the schedule, used verbatim in the reports."""
        yn = lambda y: f"Year {y - self.year_zero}"  # noqa: E731
        lines = [f"${e.amount:,.0f} contributed at the start of {e.year} ({yn(e.year)})" for e in self.contributions]
        lines += [f"${e.amount:,.0f} withdrawn at the start of {e.year} ({yn(e.year)})" for e in self.withdrawals]
        if not self.withdrawals:
            lines.append(f"no withdrawals before the operating reserve is set aside in {self.reserve_setup_year}")
        n = len(self.payments)
        lines.append(f"operating reserve set aside at the start of {self.reserve_setup_year} "
                     f"({yn(self.reserve_setup_year)}), before the first payment")
        lines.append(f"{n} operating payments of ${self.payment_amount:,.0f} (fixed, not inflation-adjusted), "
                     f"one at the start of each year {self.first_payment_year}-{self.last_payment_year}")
        return lines


# ------------------------------------------------------------------------------ building
def _events(rows, kind: str) -> list[CashflowEvent]:
    out = []
    for i, r in enumerate(rows or []):
        try:
            year, amount = int(r["year"]), float(r["amount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CashflowError(f"cashflows.{kind}s[{i}] needs integer 'year' and numeric 'amount': {r!r}") from exc
        timing = str(r.get("timing", "start")).lower()
        if timing != "start":
            raise CashflowError(f"cashflows.{kind}s[{i}] ({year}): timing '{timing}' not allowed; "
                                "the case requires all flows at the beginning of the year")
        if amount <= 0:
            raise CashflowError(f"cashflows.{kind}s[{i}] ({year}): amount must be positive, got {amount}")
        out.append(CashflowEvent(year, amount, kind))
    return sorted(out, key=lambda e: e.year)


def build_schedule(cfg: dict) -> CashflowSchedule:
    """Build and structurally validate the schedule from `cfg['cashflows']`."""
    cf, sim = cfg["cashflows"], cfg["simulation"]
    rp = cf["reserve_payments"]
    if str(rp.get("timing", "start")).lower() != "start":
        raise CashflowError("cashflows.reserve_payments.timing must be 'start' (payments are at the beginning of each year)")
    first, last, amount = int(rp["first_year"]), int(rp["last_year"]), float(rp["amount"])
    if last < first or amount <= 0:
        raise CashflowError(f"cashflows.reserve_payments: need last_year >= first_year and amount > 0 (got {first}-{last}, {amount})")
    payments = [CashflowEvent(y, amount, "operating_payment") for y in range(first, last + 1)]

    sched = CashflowSchedule(
        year_zero=int(cf.get("year_zero", 2026)),
        start_year=int(sim["start_year"]),
        reserve_setup_year=int(cf.get("reserve_setup_year", sim["glide_end_year"])),
        checkpoint_year=int(cf.get("sponsor_checkpoint_year", 2031)),
        contributions=_events(cf.get("contributions"), "contribution"),
        withdrawals=_events(cf.get("withdrawals"), "withdrawal"),
        payments=payments,
    )

    if not sched.contributions:
        raise CashflowError("cashflows.contributions is empty: nothing would ever be invested")
    if sched.reserve_setup_year != sim["glide_end_year"]:
        raise CashflowError(f"reserve_setup_year ({sched.reserve_setup_year}) must equal simulation.glide_end_year "
                            f"({sim['glide_end_year']}): the reserve is carved out when the growth phase ends")
    if first != sched.reserve_setup_year:
        raise CashflowError(f"first operating payment ({first}) must fall in the reserve set-up year "
                            f"({sched.reserve_setup_year}): the reserve is set aside just before payment 1")
    if sim["reserve_end_year"] != last:
        raise CashflowError(f"simulation.reserve_end_year ({sim['reserve_end_year']}) must equal the last "
                            f"operating payment year ({last})")
    for e in sched.contributions + sched.withdrawals:
        if e.year < sched.start_year:
            raise CashflowError(f"{e.kind} in {e.year} is before simulation.start_year ({sched.start_year})")
        if e.year >= sched.reserve_setup_year:
            raise CashflowError(f"{e.kind} in {e.year}: contributions/withdrawals are only modelled before the "
                                f"{sched.reserve_setup_year} reserve set-up (after it, only the operating payments move money)")
    if not (sched.start_year < sched.checkpoint_year < sched.reserve_setup_year):
        raise CashflowError(f"sponsor_checkpoint_year ({sched.checkpoint_year}) must lie between "
                            f"{sched.start_year} and {sched.reserve_setup_year}")
    return sched


# ------------------------------------------------------------------------ case compliance
def case_violations(sched: CashflowSchedule, rules: dict) -> list[str]:
    """Differences between the schedule and the case rules in `cfg['case_rules']`."""
    v: list[str] = []
    if sched.year_zero != rules["year_zero"]:
        v.append(f"year_zero is {sched.year_zero}; the case defines 2026 = Year 0 ({rules['year_zero']})")

    want = {int(y): float(a) for y, a in rules["contributions"].items()}
    got: dict[int, float] = {}
    for e in sched.contributions:
        got[e.year] = got.get(e.year, 0.0) + e.amount
    for y in sorted(set(want) | set(got)):
        if got.get(y, 0.0) != want.get(y, 0.0):
            v.append(f"contribution {y}: schedule has ${got.get(y, 0.0):,.0f}, case says ${want.get(y, 0.0):,.0f}")

    if sched.withdrawals and rules.get("no_other_flows_before_reserve", True):
        years = ", ".join(str(e.year) for e in sched.withdrawals)
        v.append(f"withdrawal(s) in {years}: the case allows none before the {sched.reserve_setup_year} reserve")

    op = rules["operating_payment"]
    if sched.payment_amount != float(op["amount"]):
        v.append(f"operating payment is ${sched.payment_amount:,.0f}; case says a fixed ${op['amount']:,.0f}")
    if len(sched.payments) != int(op["count"]):
        v.append(f"{len(sched.payments)} operating payments; the case says {op['count']}")
    if sched.first_payment_year != int(op["first_year"]):
        v.append(f"first operating payment {sched.first_payment_year}; case says {op['first_year']}")
    if sched.reserve_setup_year != int(op["first_year"]):
        v.append(f"reserve set-up year {sched.reserve_setup_year}; case says {op['first_year']}")
    if sched.checkpoint_year != int(rules["sponsor_checkpoint_year"]):
        v.append(f"sponsor checkpoint {sched.checkpoint_year}; case says {rules['sponsor_checkpoint_year']}")
    return v


def validated_schedule(cfg: dict) -> CashflowSchedule:
    """Build the schedule; if `case_rules.enforce` is true, refuse anything the case does not allow."""
    sched = build_schedule(cfg)
    rules = cfg.get("case_rules")
    if rules and rules.get("enforce", True):
        problems = case_violations(sched, rules)
        if problems:
            raise CashflowError(
                "Cash flows contradict the case rules (" + rules.get("source", "case") + "):\n  - "
                + "\n  - ".join(problems)
                + "\nFix cashflows in the config, or set case_rules.enforce: false for a what-if run.")
    return sched
