from autojob.search.feeds import parse_wwr
from autojob.search.jobs import Connector

def test_wwr_feed():
 content=b'<rss><channel><item><title>Example: Python Developer</title><link>https://weworkremotely.com/jobs/example</link><guid>id-1</guid><description>Remote worldwide. Python required.</description><pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'
 payload=parse_wwr(content);jobs=list(Connector('We Work Remotely').search_jobs(['Python'],payload=payload))
 assert len(jobs)==1 and jobs[0]['company']=='Example' and jobs[0]['title']=='Python Developer'
 # Worldwide es un indicio; esta corrección exige verificar Costa Rica.
 assert jobs[0]['geography']=='POSIBLE' and jobs[0]['published_at'].startswith('2026-10-30')
