//! Filang spot ledger v1: fully cash-funded long/flat, close decision -> next open.
//! The entry fee is paid out of the cash budget, not borrowed. Flat cash earns zero.
use crate::{data::Data, Result};

#[derive(Clone, Copy, Debug)]
pub struct Costs {
    pub fee_bps: f64,
    pub slip_bps: f64,
}
impl Costs {
    pub fn validate(self) -> Result<Self> {
        if !self.fee_bps.is_finite()
            || !self.slip_bps.is_finite()
            || !(0.0..1000.0).contains(&self.fee_bps)
            || !(0.0..1000.0).contains(&self.slip_bps)
        {
            return Err("fees/slippage must be finite and in [0,1000) bps".into());
        }
        Ok(self)
    }
    fn multipliers(self) -> (f64, f64) {
        let f = self.fee_bps / 10000.0;
        let s = self.slip_bps / 10000.0;
        (1.0 / ((1.0 + f) * (1.0 + s)), (1.0 - f) * (1.0 - s))
    }
}
#[derive(Clone, Copy, Debug)]
pub struct Rule {
    pub threshold: f64,
    pub greater: bool,
}
impl Rule {
    pub fn active(self, x: f64) -> bool {
        x.is_finite()
            && if self.greater {
                x > self.threshold
            } else {
                x < self.threshold
            }
    }
}
#[derive(Clone, Copy, Debug, Default)]
pub struct Lite {
    pub periods: usize,
    pub entries: usize,
    pub active: usize,
    pub log_return: f64,
    pub sum: f64,
    pub sum_sq: f64,
}
impl Lite {
    pub fn exposure(self) -> f64 {
        self.active as f64 / self.periods.max(1) as f64
    }
    pub fn sharpe(self, interval: i64) -> f64 {
        let n = self.periods as f64;
        if n < 2.0 {
            return f64::NAN;
        }
        let mean = self.sum / n;
        let var = ((self.sum_sq - n * mean * mean) / (n - 1.0)).max(0.0);
        if var > 1e-24 {
            mean / var.sqrt() * (31557600.0 / interval as f64).sqrt()
        } else {
            f64::NAN
        }
    }
    pub fn return_pct(self) -> f64 {
        self.log_return.exp_m1() * 100.0
    }
}
#[derive(Clone, Debug)]
pub struct Metrics {
    pub lite: Lite,
    pub gross_return_pct: f64,
    pub max_drawdown_pct: f64,
    pub cagr_pct: f64,
    pub mean_trade_bps: f64,
}
/// A period t uses x[t], enters no earlier than open[t+1], earns open[t+2]/open[t+1].
/// start/end delimit input bars; final two decisions lack a complete execution interval.
pub struct Market {
    pub start: usize,
    pub len: usize,
    pub interval: i64,
    gross: Vec<f64>,
    terms: Vec<[[f64; 3]; 4]>,
}
impl Market {
    pub fn new(d: &Data, start: usize, end: usize, cost: Costs) -> Result<Self> {
        cost.validate()?;
        if start >= end
            || end > d.len()
            || end - start < 4
            || d.interval <= 0
            || d.columns.iter().any(|c| c.len() != d.len())
        {
            return Err("evaluation range must contain >=4 bars".into());
        }
        let len = end - start - 2;
        let (entry, exit) = cost.multipliers();
        let mult = [1.0, entry, exit, entry * exit];
        let mut gross = Vec::with_capacity(len);
        let mut terms = Vec::with_capacity(len);
        for t in start..start + len {
            let a = d.columns[0][t + 2] / d.columns[0][t + 1];
            if !a.is_finite() || a <= 0.0 {
                return Err("nonfinite or nonpositive price growth".into());
            }
            gross.push(a);
            terms.push(std::array::from_fn(|c| {
                let factor = a * mult[c];
                let r = factor - 1.0;
                [factor.ln(), r, r * r]
            }));
        }
        Ok(Self {
            start,
            len,
            interval: d.interval,
            gross,
            terms,
        })
    }
    fn validate_series(&self, x: &[f64], rules: &[Rule]) -> Result<()> {
        if x.len() < self.start + self.len {
            return Err("feature shorter than evaluation range".into());
        }
        if rules.iter().any(|r| !r.threshold.is_finite()) {
            return Err("threshold must be finite".into());
        }
        Ok(())
    }
    pub fn score(&self, x: &[f64], rule: Rule) -> Result<Metrics> {
        self.validate_series(x, &[rule])?;
        Ok(self.replay(x, rule))
    }
    pub fn score_thresholds(&self, x: &[f64], rules: &[Rule]) -> Result<Vec<Lite>> {
        self.validate_series(x, rules)?;
        Ok(self.sweep(x, rules))
    }
    pub fn score_direct_summaries(&self, x: &[f64], rules: &[Rule]) -> Result<Vec<Lite>> {
        self.validate_series(x, rules)?;
        Ok(rules.iter().map(|r| self.direct_lite(x, *r)).collect())
    }
    /// One activation sweep, cost-independent category moments, many cost scenarios.
    /// No sorting/history scan is repeated for a changed fee/slippage pair.
    pub fn score_scenarios(
        &self,
        x: &[f64],
        rules: &[Rule],
        costs: &[Costs],
    ) -> Result<Vec<Vec<Lite>>> {
        self.validate_series(x, rules)?;
        for cost in costs {
            cost.validate()?;
        }
        let mut values = (0..self.len)
            .filter_map(|t| {
                let v = x[self.start + t];
                if v.is_finite() {
                    Some((v, t))
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        values.sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
        let mut out = vec![vec![Lite::default(); rules.len()]; costs.len()];
        for greater in [false, true] {
            let mut queries = (0..rules.len())
                .filter(|i| rules[*i].greater == greater)
                .collect::<Vec<_>>();
            queries.sort_unstable_by(|i, j| {
                let o = rules[*i]
                    .threshold
                    .partial_cmp(&rules[*j].threshold)
                    .unwrap();
                if greater {
                    o.reverse()
                } else {
                    o
                }
            });
            let mut pos = vec![false; self.len];
            let mut next = 0;
            let mut stats = FreeStats::default();
            for qi in queries {
                while next < values.len() {
                    let vi = if greater {
                        values.len() - 1 - next
                    } else {
                        next
                    };
                    let (v, t) = values[vi];
                    if !rules[qi].active(v) {
                        break;
                    }
                    let lo = t.saturating_sub(1);
                    let hi = (t + 2).min(self.len);
                    for j in lo..hi {
                        if pos[j] {
                            let cat = (j == 0 || !pos[j - 1]) as usize
                                + 2 * ((j + 1 == pos.len() || !pos[j + 1]) as usize);
                            stats.update(cat, self.gross[j], -1);
                        }
                    }
                    pos[t] = true;
                    for j in lo..hi {
                        if pos[j] {
                            let cat = (j == 0 || !pos[j - 1]) as usize
                                + 2 * ((j + 1 == pos.len() || !pos[j + 1]) as usize);
                            stats.update(cat, self.gross[j], 1);
                        }
                    }
                    next += 1;
                }
                for (ci, &cost) in costs.iter().enumerate() {
                    out[ci][qi] = stats.render(self.len, cost);
                }
            }
        }
        Ok(out)
    }
    /// Explicit complete-period ledger, used by chronological portfolio replay.
    pub fn position_ledger(&self, p: &[bool]) -> Result<Vec<Period>> {
        if p.len() != self.len {
            return Err("position length differs from execution range".into());
        }
        Ok((0..p.len())
            .map(|t| {
                if !p[t] {
                    return Period::default();
                }
                let entry = t == 0 || !p[t - 1];
                let exit = t + 1 == p.len() || !p[t + 1];
                let cat = entry as usize + 2 * exit as usize;
                Period {
                    net: self.terms[t][cat][1],
                    gross: self.gross[t] - 1.0,
                    active: true,
                    entry,
                    exit,
                }
            })
            .collect())
    }
    fn contribution(&self, p: &[bool], t: usize) -> (usize, usize, [f64; 3]) {
        if !p[t] {
            return (0, 0, [0.0; 3]);
        }
        let entry = t == 0 || !p[t - 1];
        let exit = t + 1 == p.len() || !p[t + 1];
        let c = entry as usize + 2 * exit as usize;
        (1, entry as usize, self.terms[t][c])
    }
    pub(crate) fn direct_lite(&self, x: &[f64], rule: Rule) -> Lite {
        let p = (0..self.len)
            .map(|t| rule.active(x[self.start + t]))
            .collect::<Vec<_>>();
        let mut s = Lite {
            periods: self.len,
            ..Lite::default()
        };
        for t in 0..self.len {
            let (a, e, c) = self.contribution(&p, t);
            s.active += a;
            s.entries += e;
            s.log_return += c[0];
            s.sum += c[1];
            s.sum_sq += c[2];
        }
        s
    }
    /// Full chronological replay, including drawdown and completed-trade returns.
    pub(crate) fn replay(&self, x: &[f64], rule: Rule) -> Metrics {
        let p = (0..self.len)
            .map(|t| rule.active(x[self.start + t]))
            .collect::<Vec<_>>();
        let mut lite = Lite {
            periods: self.len,
            ..Lite::default()
        };
        let (mut peak, mut max_dd, mut loggross, mut tradelog, mut tradesum) =
            (0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64);
        for t in 0..self.len {
            let (a, e, c) = self.contribution(&p, t);
            lite.active += a;
            lite.entries += e;
            lite.log_return += c[0];
            lite.sum += c[1];
            lite.sum_sq += c[2];
            peak = peak.max(lite.log_return);
            max_dd = max_dd.max(peak - lite.log_return);
            if p[t] {
                loggross += self.gross[t].ln();
                tradelog += c[0];
                if t + 1 == self.len || !p[t + 1] {
                    tradesum += tradelog.exp_m1();
                    tradelog = 0.0;
                }
            }
        }
        Metrics {
            lite,
            gross_return_pct: loggross.exp_m1() * 100.0,
            max_drawdown_pct: -(-max_dd).exp_m1() * 100.0,
            cagr_pct: (lite.log_return * 31557600.0 / (self.len as f64 * self.interval as f64))
                .exp_m1()
                * 100.0,
            mean_trade_bps: if lite.entries > 0 {
                tradesum / lite.entries as f64 * 10000.0
            } else {
                f64::NAN
            },
        }
    }
    /// Sweep parameter events instead of rescanning the whole history per threshold.
    /// Only t-1,t,t+1 contributions change on a position-bit activation.
    pub(crate) fn sweep(&self, x: &[f64], rules: &[Rule]) -> Vec<Lite> {
        let mut values = (0..self.len)
            .filter_map(|t| {
                let v = x[self.start + t];
                if v.is_finite() {
                    Some((v, t))
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        values.sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
        let mut answers = vec![Lite::default(); rules.len()];
        for greater in [false, true] {
            let mut queries = (0..rules.len())
                .filter(|i| rules[*i].greater == greater)
                .collect::<Vec<_>>();
            queries.sort_unstable_by(|i, j| {
                let ord = rules[*i]
                    .threshold
                    .partial_cmp(&rules[*j].threshold)
                    .unwrap();
                if greater {
                    ord.reverse()
                } else {
                    ord
                }
            });
            let mut p = vec![false; self.len];
            let mut next = 0;
            let mut active = 0isize;
            let mut entries = 0isize;
            let mut sums = [Kahan::default(); 3];
            for qi in queries {
                let rule = rules[qi];
                while next < values.len() {
                    let vi = if greater {
                        values.len() - 1 - next
                    } else {
                        next
                    };
                    let (v, t) = values[vi];
                    if !rule.active(v) {
                        break;
                    }
                    let lo = t.saturating_sub(1);
                    let hi = (t + 2).min(self.len);
                    for j in lo..hi {
                        let (a, e, c) = self.contribution(&p, j);
                        active -= a as isize;
                        entries -= e as isize;
                        for k in 0..3 {
                            sums[k].add(-c[k]);
                        }
                    }
                    p[t] = true;
                    for j in lo..hi {
                        let (a, e, c) = self.contribution(&p, j);
                        active += a as isize;
                        entries += e as isize;
                        for k in 0..3 {
                            sums[k].add(c[k]);
                        }
                    }
                    next += 1;
                }
                answers[qi] = Lite {
                    periods: self.len,
                    entries: entries as usize,
                    active: active as usize,
                    log_return: sums[0].sum,
                    sum: sums[1].sum,
                    sum_sq: sums[2].sum,
                };
            }
        }
        answers
    }
}
#[derive(Clone, Copy, Debug, Default)]
pub struct Period {
    pub net: f64,
    pub gross: f64,
    pub active: bool,
    pub entry: bool,
    pub exit: bool,
}
/// Includes explicit flat gaps between rebalance windows; no hidden gap compounding.
pub fn metrics_from_ledger(rows: &[Period], interval: i64) -> Result<Metrics> {
    if rows.is_empty()
        || interval <= 0
        || rows
            .iter()
            .any(|r| !r.net.is_finite() || r.net <= -1.0 || !r.gross.is_finite() || r.gross <= -1.0)
    {
        return Err("invalid chronological ledger".into());
    }
    let mut lite = Lite {
        periods: rows.len(),
        ..Lite::default()
    };
    let (mut peak, mut dd, mut gross, mut trade, mut trade_sum) =
        (0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64);
    for r in rows {
        lite.active += r.active as usize;
        lite.entries += r.entry as usize;
        lite.log_return += r.net.ln_1p();
        lite.sum += r.net;
        lite.sum_sq += r.net * r.net;
        gross += r.gross.ln_1p();
        peak = peak.max(lite.log_return);
        dd = dd.max(peak - lite.log_return);
        if r.active {
            trade += r.net.ln_1p();
            if r.exit {
                trade_sum += trade.exp_m1();
                trade = 0.0;
            }
        }
    }
    Ok(Metrics {
        lite,
        gross_return_pct: gross.exp_m1() * 100.0,
        max_drawdown_pct: -(-dd).exp_m1() * 100.0,
        cagr_pct: (lite.log_return * 31557600.0 / (rows.len() as f64 * interval as f64)).exp_m1()
            * 100.0,
        mean_trade_bps: if lite.entries > 0 {
            trade_sum / lite.entries as f64 * 10000.0
        } else {
            f64::NAN
        },
    })
}
#[derive(Clone, Copy, Default)]
struct FreeStats {
    count: [isize; 4],
    returns: [Kahan; 4],
    squares: [Kahan; 4],
    log: Kahan,
}
impl FreeStats {
    fn update(&mut self, cat: usize, growth: f64, sign: isize) {
        let r = growth - 1.0;
        self.count[cat] += sign;
        self.returns[cat].add(sign as f64 * r);
        self.squares[cat].add(sign as f64 * r * r);
        self.log.add(sign as f64 * growth.ln());
    }
    fn render(&self, periods: usize, cost: Costs) -> Lite {
        let (en, ex) = cost.multipliers();
        let multipliers = [1.0, en, ex, en * ex];
        let entries = (self.count[1] + self.count[3]) as usize;
        let exits = (self.count[2] + self.count[3]) as usize;
        let (mut sum, mut sum_sq) = (0.0, 0.0);
        for (i, &m) in multipliers.iter().enumerate() {
            let c = self.count[i] as f64;
            let delta = m - 1.0;
            sum += m * self.returns[i].sum + c * delta;
            sum_sq += m * m * self.squares[i].sum
                + 2.0 * m * delta * self.returns[i].sum
                + c * delta * delta;
        }
        Lite {
            periods,
            entries,
            active: self.count.iter().sum::<isize>() as usize,
            log_return: self.log.sum + entries as f64 * en.ln() + exits as f64 * ex.ln(),
            sum,
            sum_sq,
        }
    }
}
#[derive(Clone, Copy, Default)]
struct Kahan {
    sum: f64,
    c: f64,
}
impl Kahan {
    fn add(&mut self, x: f64) {
        let y = x - self.c;
        let t = self.sum + y;
        self.c = (t - self.sum) - y;
        self.sum = t;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn data() -> Data {
        Data {
            timestamps: (0..20).collect(),
            columns: std::array::from_fn(|_| {
                (0..20)
                    .map(|i| 100.0 * (1.0 + 0.01 * (i as f64).sin()))
                    .collect()
            }),
            interval: 1,
            digest: "test".into(),
        }
    }
    #[test]
    fn sweep_matches_direct_ties_costs_and_invalid() {
        let d = data();
        for fee in [0.0, 5.0, 50.0] {
            for slip in [0.0, 5.0, 30.0] {
                let m = Market::new(
                    &d,
                    0,
                    20,
                    Costs {
                        fee_bps: fee,
                        slip_bps: slip,
                    },
                )
                .unwrap();
                for seed in 0..100 {
                    let x = (0..20)
                        .map(|i| {
                            if (i + seed) % 13 == 0 {
                                f64::NAN
                            } else {
                                ((i * 19 + seed * 7) % 11) as f64 / 5.0 - 1.0
                            }
                        })
                        .collect::<Vec<_>>();
                    let rules = (-12..=12)
                        .flat_map(|j| {
                            [false, true].map(move |greater| Rule {
                                threshold: j as f64 / 10.0,
                                greater,
                            })
                        })
                        .collect::<Vec<_>>();
                    let fast = m.sweep(&x, &rules);
                    for (i, r) in rules.iter().enumerate() {
                        let exact = m.direct_lite(&x, *r);
                        let f = fast[i];
                        assert_eq!((exact.active, exact.entries), (f.active, f.entries));
                        assert!((exact.log_return - f.log_return).abs() < 1e-12);
                        assert!((exact.sum - f.sum).abs() < 1e-12);
                        assert!((exact.sum_sq - f.sum_sq).abs() < 1e-12);
                    }
                }
            }
        }
    }
    #[test]
    fn cash_and_cash_funded_buy_hold() {
        let d = data();
        let c = Costs {
            fee_bps: 10.0,
            slip_bps: 20.0,
        };
        let m = Market::new(&d, 0, 20, c).unwrap();
        let on = vec![1.0; 20];
        let a = m.replay(
            &on,
            Rule {
                threshold: 0.0,
                greater: true,
            },
        );
        let (en, ex) = c.multipliers();
        let expected = d.columns[0][19] / d.columns[0][1] * en * ex;
        assert!((a.lite.log_return.exp() - expected).abs() < 1e-12);
        assert_eq!(a.lite.entries, 1);
        let flat = m.replay(
            &on,
            Rule {
                threshold: 2.0,
                greater: true,
            },
        );
        assert_eq!(flat.lite.return_pct(), 0.0);
        assert_eq!(flat.max_drawdown_pct, 0.0);
    }
    #[test]
    fn shared_cost_scenarios_match_independent_ledgers() {
        let d = data();
        let costs = [
            Costs {
                fee_bps: 0.0,
                slip_bps: 0.0,
            },
            Costs {
                fee_bps: 5.0,
                slip_bps: 5.0,
            },
            Costs {
                fee_bps: 50.0,
                slip_bps: 70.0,
            },
        ];
        let m = Market::new(&d, 0, d.len(), costs[0]).unwrap();
        let rules = (-10..=10)
            .flat_map(|j| {
                [false, true].map(move |greater| Rule {
                    greater,
                    threshold: j as f64 / 10.0,
                })
            })
            .collect::<Vec<_>>();
        for seed in 0..50 {
            let x = (0..d.len())
                .map(|i| {
                    if (i + seed) % 13 == 0 {
                        f64::NAN
                    } else {
                        ((i * 23 + seed * 17) % 19) as f64 / 9.0 - 1.0
                    }
                })
                .collect::<Vec<_>>();
            let fast = m.score_scenarios(&x, &rules, &costs).unwrap();
            for (ci, &cost) in costs.iter().enumerate() {
                let market = Market::new(&d, 0, d.len(), cost).unwrap();
                for (i, &r) in rules.iter().enumerate() {
                    let reference = market.score(&x, r).unwrap();
                    let f = fast[ci][i];
                    assert_eq!(
                        (f.entries, f.active),
                        (reference.lite.entries, reference.lite.active)
                    );
                    assert!((f.log_return - reference.lite.log_return).abs() < 1e-12);
                    assert!((f.sum - reference.lite.sum).abs() < 1e-12);
                    assert!((f.sum_sq - reference.lite.sum_sq).abs() < 1e-12);
                    let p = x[..market.len]
                        .iter()
                        .map(|v| r.active(*v))
                        .collect::<Vec<_>>();
                    let ledger = market.position_ledger(&p).unwrap();
                    let z = metrics_from_ledger(&ledger, 1).unwrap();
                    assert!((z.max_drawdown_pct - reference.max_drawdown_pct).abs() < 1e-11);
                }
            }
        }
    }
    #[test]
    fn no_same_bar_return() {
        let mut d = data();
        let x = (0..20)
            .map(|i| if i == 3 { 1.0 } else { 0.0 })
            .collect::<Vec<_>>();
        let costs = Costs {
            fee_bps: 0.0,
            slip_bps: 0.0,
        };
        let before = Market::new(&d, 0, 20, costs).unwrap().replay(
            &x,
            Rule {
                threshold: 0.0,
                greater: true,
            },
        );
        d.columns[0][3] *= 50.0;
        let after = Market::new(&d, 0, 20, costs).unwrap().replay(
            &x,
            Rule {
                threshold: 0.0,
                greater: true,
            },
        );
        assert_eq!(before.lite.log_return, after.lite.log_return);
    }
}
