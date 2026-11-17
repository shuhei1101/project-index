import sys,os,subprocess
sys.path.insert(0,'/tmp/pi106')
from measure_lib import md_metrics
for root in sys.argv[1:]:
    files=[f for f in subprocess.run(['git','-C',root,'ls-files','-z'],capture_output=True,text=True).stdout.split('\0') if f.endswith('.md') and os.path.isfile(os.path.join(root,f))]
    m=[md_metrics(open(os.path.join(root,f),errors='ignore').read()) for f in files]
    for H,C,J in [(2,0.5,0.1),(3,0.5,0.1),(2,0.4,0.1),(2,0.5,0.2)]:
        n=sum(1 for h,c,j in m if h<H or c>=C or j<J)
        print(root.split('/')[4],H,C,J,n,len(m))
    big=sorted(((os.path.getsize(os.path.join(root,f)),f) for f in subprocess.run(['git','-C',root,'ls-files','-z'],capture_output=True,text=True).stdout.split('\0') if f and os.path.isfile(os.path.join(root,f))),reverse=True)[:3]
    print(big)
