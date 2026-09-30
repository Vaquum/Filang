/* Independent cash/share reference; no Filang includes or tree algebra. */
#include <math.h>
#include <stddef.h>
#include <stdbool.h>
int cohort_ledger(const double *q, size_t n, const double *prices,
                  const double *cutoffs, size_t nc, double fee, double slip,
                  double interval, double *out) {
    if(n<2 || interval<=0) return 1;
    for(size_t k=0;k<nc;k++) {
        double cash=1,shares=0,previous=1,peak=1,dd=0,entry_eq=1,trade_sum=0;
        double sum=0,squares=0,gross=1;
        size_t trades=0,active_count=0;bool prior=false;
        for(size_t t=0;t<n;t++) {
            double f=q[t]-cutoffs[k];bool active=isfinite(f)&&f>0;
            double next_f=t+1<n?q[t+1]-cutoffs[k]:NAN;
            bool next=t+1<n&&isfinite(next_f)&&next_f>0;
            if(active && !prior) {
                entry_eq=cash;shares=cash/(prices[t]*(1+slip)*(1+fee));
                cash=0;trades++;
            }
            double equity=cash+shares*prices[t+1];
            if(active && !next) {
                cash=shares*prices[t+1]*(1-slip)*(1-fee);shares=0;
                equity=cash;trade_sum+=equity/entry_eq-1;
            }
            double r=equity/previous-1;sum+=r;squares+=r*r;
            if(equity>peak) peak=equity;
            double drawdown=1-equity/peak;if(drawdown>dd) dd=drawdown;
            if(active) {gross*=prices[t+1]/prices[t];active_count++;}
            previous=equity;prior=active;
        }
        double mean=sum/n,var=(squares-n*mean*mean)/(n-1),*v=out+10*k;
        v[0]=(previous-1)*100;v[1]=(gross-1)*100;
        v[2]=expm1(log(previous)*31557600.0/(n*interval))*100;v[3]=dd*100;
        v[4]=var>1e-24?mean/sqrt(var)*sqrt(31557600.0/interval):NAN;
        v[5]=(double)trades;v[6]=100.0*active_count/n;v[7]=mean*10000;
        v[8]=trades?10000*trade_sum/trades:NAN;v[9]=(double)n;
    }
    return 0;
}
