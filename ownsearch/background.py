"""Bounded daemon discovery for long-lived API processes. CLI explicitly awaits discovery."""
import threading
import time

class DiscoveryJobs:
    def __init__(self,maximum=2):
        self.lock=threading.Lock();self.jobs={};self.maximum=maximum
    def submit(self,key,work):
        with self.lock:
            old=self.jobs.get(key)
            if old and (old['state'] in ('queued','running') or time.monotonic()-old['updated']<30): return dict(old)
            if sum(v['state'] in ('queued','running') for v in self.jobs.values())>=self.maximum:
                return {'state':'busy','errors':['Background discovery capacity reached.']}
            state={'state':'queued','updated':time.monotonic(),'errors':[]};self.jobs[key]=state
            if len(self.jobs)>256:
                for k in list(self.jobs):
                    if self.jobs[k]['state'] not in ('queued','running') and k!=key: self.jobs.pop(k)
                    if len(self.jobs)<=256:break
        def run():
            with self.lock:state.update(state='running',updated=time.monotonic())
            try:
                result,errors=work()
                with self.lock:state.update(state='complete' if result else 'unavailable',results=result,errors=errors,updated=time.monotonic())
            except Exception as exc:
                with self.lock:state.update(state='failed',errors=[str(exc)],updated=time.monotonic())
        threading.Thread(target=run,name='ownsearch-discovery',daemon=True).start()
        return {'state':'queued','errors':[]}
