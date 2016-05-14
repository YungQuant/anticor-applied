import os
import os.path

from pyalgotrade.tools import yahoofinance

dir = 'data'
if not os.path.isdir(dir): os.makedirs(dir)

years = [2016]
for year in years:
    with open("atleast20.txt", "r") as ins:
        for line in ins:
            s = line.strip()
            file_name = "%s/%s - %s.csv" % (dir, s, year)
            try:
                if not os.path.isfile(file_name):
                    yahoofinance.download_daily_bars(s, year, file_name)
            except:
                print "ERROR => %s" % s
