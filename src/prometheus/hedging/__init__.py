"""Deep hedging and stochastic control (section 07).

Current scope (PR-007): a Black-Scholes delta baseline, a cost-aware
no-trade-band variant, a shared self-financing discrete-time hedge
simulator used by both, and a first MLP hedging policy trained to minimize
CVaR of terminal loss plus a turnover penalty (Buehler et al., 2019 [R01]).
All of them -- baseline and learned -- are evaluated through the same
simulate.simulate_self_financing_hedge function, with the same transaction
cost rate and the same price paths, specifically so a policy cannot look
better than delta hedging merely by using more leverage, lower costs, or a
different information set (HDG-13).
"""
