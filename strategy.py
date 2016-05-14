import os
import datetime

from pyalgotrade.broker.backtesting import FixedPerTrade

import algorithm
import numpy as np
import pandas.io.data as web

from pyalgotrade import strategy
from pyalgotrade.barfeed import yahoofeed
from pyalgotrade.stratanalyzer import sharpe
from pyalgotrade.stratanalyzer import drawdown
from pyalgotrade.stratanalyzer import trades

class MyStrategy(strategy.BacktestingStrategy):
    def __init__(self, feed, instruments, window_size):
        strategy.BacktestingStrategy.__init__(self, feed, 1000)
        self.__instruments = instruments

        self.__process = algorithm.Algo()
        self.__process_window = window_size
        self.__target_portfolio = []
        self.__current_window = []
        self.__rebalance_frequency = 10
        self.__rebalance_i = 0

        self.__positions = {}
        for instrument in self.__instruments:
            self.__positions[instrument] = []
        # We'll use adjusted close values instead of regular close values.
        self.setUseAdjustedValues(False)

    def initialize(self):
        start = datetime.datetime(2015, 1, 1)
        end = datetime.datetime(2016, 1, 1)

        data = web.DataReader(self.__instruments, 'yahoo', start, end).Close
        data = data.fillna(method='pad')
        data = data.fillna(method='bfill')

        v = data.values
        x = v[1:] / v[:-1]

        # Initialize portfolio weights and historical weights to uniform
        s = x.shape
        m = s[1]
        self.__target_portfolio = np.ones(m) * 1.0 / m

        # The primary control statement for the anticor algorithm, for each day obtain the weights and save them in our hist_weights matrix
        for t in range(s[0] - 1):
            self.__target_portfolio = self.__process.anticor(self.__process_window, t, x, self.__target_portfolio, True)
            self.__current_window = v[t - (2 * self.__process_window) + 1:t + 1, :]
        print self.__target_portfolio

    def onEnterOk(self, position):
        execInfo = position.getEntryOrder().getExecutionInfo()
        self.info("BUY '%s' at $%.2f" % (position.getInstrument(), execInfo.getPrice()))

    def onEnterCanceled(self, position):
        instrument = position.getInstrument()
        self.__positions[instrument].remove(position)

    def onExitOk(self, position):
        execInfo = position.getExitOrder().getExecutionInfo()
        self.info("SELL '%s' at $%.2f" % (position.getInstrument(), execInfo.getPrice()))

    def onExitCanceled(self, position):
        # If the exit was canceled, re-submit it.
        position.exitMarket()

    def interpolate_nans(self, X):
        """Overwrite NaNs with column value interpolations."""
        for j in range(X.shape[1]):
            mask_j = np.isnan(X[:, j])
            X[mask_j, j] = np.interp(np.flatnonzero(mask_j), np.flatnonzero(~mask_j), X[~mask_j, j])
        return X

    def onBars(self, bars):
        self.__rebalance_i += 1
        if (self.__rebalance_i > self.__rebalance_frequency):
            self.__rebalance_i = 0
            arr = []
            for instrument in self.__instruments:
                if instrument in bars:
                    arr.append(bars[instrument].getPrice())
                else:
                    arr.append(np.nan)
            self.__current_window = np.vstack((self.__current_window, np.array(arr))) # append the new prices to the end of our current_window
            self.__current_window = self.__current_window[1:] # take everything except the first row of the new window
            self.__current_window = self.interpolate_nans(self.__current_window) # replace empty values with logical values

            v = self.__current_window[1:]
            x = v[1:] / v[:-1] # calculate relative prices
            t = 0
            self.__target_portfolio = self.__process.anticor(self.__process_window, t, x, self.__target_portfolio, True)

            total_value = self.getBroker().getCash()
            for instrument, price in zip(self.__instruments, self.__current_window[:][-1]):
                shares = self.getBroker().getShares(instrument)
                total_value += shares * price

            for instrument, target in zip(self.__instruments, self.__target_portfolio):
                if instrument in bars:
                    bar = bars[instrument]
                    shares = self.getBroker().getShares(instrument)
                    price_p_share = bar.getPrice()
                    value_in_shares = shares * price_p_share
                    budget = total_value * target

                    if price_p_share < budget - value_in_shares:
                        order_size = (budget - value_in_shares) // price_p_share
                        ordered = 0
                        while ordered < order_size:
                            new_order = order_size // self.__process_window
                            if new_order == 0:
                                new_order = 1
                            ordered += new_order
                            self.__positions[instrument].append(self.enterLong(instrument, new_order, True))

                    while len(self.__positions[instrument]) > 0 and value_in_shares > budget:
                        position = self.__positions[instrument][0]
                        value = (position.getQuantity() * price_p_share)
                        value_in_shares -= value
                        position.exitMarket()
                        if position in self.__positions[instrument]:
                            self.__positions[instrument].remove(position)

def run_strategy(window_size):
    # Load the yahoo feed from the CSV file
    feed = yahoofeed.Feed()
    dir = 'data'
    instruments = []
    for i in os.listdir(dir):
        if i.endswith(".csv"):
            ##print i
            name = i.split('-')[0].strip()
            instruments.append(name)
            print 'loading file:' + name
            feed.addBarsFromCSV(name, "%s/%s" % (dir, i))

    # Evaluate the strategy with the feed.
    myStrategy = MyStrategy(feed, instruments, window_size)

    # Attach different analyzers to a strategy before executing it.
    sharpeRatioAnalyzer = sharpe.SharpeRatio()
    myStrategy.attachAnalyzer(sharpeRatioAnalyzer)
    drawDownAnalyzer = drawdown.DrawDown()
    myStrategy.attachAnalyzer(drawDownAnalyzer)
    tradesAnalyzer = trades.Trades()
    myStrategy.attachAnalyzer(tradesAnalyzer)

    myStrategy.getBroker().setCash(10000)
    # As soon as you apply commision rates, you can no longer beat the market
    myStrategy.getBroker().setCommission(FixedPerTrade(6.0))
    myStrategy.initialize()

    # Run the strategy.
    myStrategy.run()

    print "Final portfolio value: $%.2f" % myStrategy.getResult()
    print "Sharpe ratio: %.2f" % (sharpeRatioAnalyzer.getSharpeRatio(0.05))
    print "Max. drawdown: %.2f %%" % (drawDownAnalyzer.getMaxDrawDown() * 100)
    print "Longest drawdown duration: %s" % (drawDownAnalyzer.getLongestDrawDownDuration())

    print
    print "Total trades: %d" % (tradesAnalyzer.getCount())
    if tradesAnalyzer.getCount() > 0:
        profits = tradesAnalyzer.getAll()
        print "Avg. profit: $%2.f" % (profits.mean())
        print "Profits std. dev.: $%2.f" % (profits.std())
        print "Max. profit: $%2.f" % (profits.max())
        print "Min. profit: $%2.f" % (profits.min())
        returns = tradesAnalyzer.getAllReturns()
        print "Avg. return: %2.f %%" % (returns.mean() * 100)
        print "Returns std. dev.: %2.f %%" % (returns.std() * 100)
        print "Max. return: %2.f %%" % (returns.max() * 100)
        print "Min. return: %2.f %%" % (returns.min() * 100)

    print
    print "Profitable trades: %d" % (tradesAnalyzer.getProfitableCount())
    if tradesAnalyzer.getProfitableCount() > 0:
        profits = tradesAnalyzer.getProfits()
        print "Avg. profit: $%2.f" % (profits.mean())
        print "Profits std. dev.: $%2.f" % (profits.std())
        print "Max. profit: $%2.f" % (profits.max())
        print "Min. profit: $%2.f" % (profits.min())
        returns = tradesAnalyzer.getPositiveReturns()
        print "Avg. return: %2.f %%" % (returns.mean() * 100)
        print "Returns std. dev.: %2.f %%" % (returns.std() * 100)
        print "Max. return: %2.f %%" % (returns.max() * 100)
        print "Min. return: %2.f %%" % (returns.min() * 100)

    print
    print "Unprofitable trades: %d" % (tradesAnalyzer.getUnprofitableCount())
    if tradesAnalyzer.getUnprofitableCount() > 0:
        losses = tradesAnalyzer.getLosses()
        print "Avg. loss: $%2.f" % (losses.mean())
        print "Losses std. dev.: $%2.f" % (losses.std())
        print "Max. loss: $%2.f" % (losses.min())
        print "Min. loss: $%2.f" % (losses.max())
        returns = tradesAnalyzer.getNegativeReturns()
        print "Avg. return: %2.f %%" % (returns.mean() * 100)
        print "Returns std. dev.: %2.f %%" % (returns.std() * 100)
        print "Max. return: %2.f %%" % (returns.max() * 100)
        print "Min. return: %2.f %%" % (returns.min() * 100)


    print "Final portfolio value: $%.2f" % myStrategy.getBroker().getEquity()

run_strategy(9)