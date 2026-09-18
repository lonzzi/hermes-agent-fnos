#!/usr/bin/env python3
"""Exercise the real upstream HTTP login gate without disclosing credentials."""
import http.cookiejar, json, os, urllib.request, urllib.error
base='http://127.0.0.1:19119'
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'})
    try:
        with client.open(req,timeout=20) as r: return r.status,json.load(r)
    except urllib.error.HTTPError as e: return e.code,None
status,_=call('/api/auth/me')
assert status==401, f'Unauthenticated endpoint returned {status}'
status,_=call('/auth/password-login',{'provider':'basic','username':'admin','password':'incorrect-password'})
assert status==401, f'Invalid password returned {status}'
status,_=call('/auth/password-login',{'provider':'basic','username':'admin','password':os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD']})
assert status==200, f'Login returned {status}'
status,body=call('/api/auth/me')
assert status==200 and body['user_id']=='admin', 'Authenticated session failed'
print('Dashboard authentication checks passed')
