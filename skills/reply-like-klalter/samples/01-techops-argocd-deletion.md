# Sample 01 — TechOps / ArgoCD deletion + Monday ordering

- **Channel:** Microsoft Teams thread
- **Audience:** TechOps reviewers — Patricia Batista Duarte, Esteban Jose Herrera Vargas
- **Purpose:** confirm a technical finding, hold a merge that would break an
  environment, and propose an ordered plan for the following Monday
- **Register:** detailed technical reply to reviewers — findings first, then a
  direct ask, then a numbered plan with a warm closer

Verbatim below. Do not correct the typos, spacing, or punctuation.

```
checked the transformer to make sure.. there's no "deletion path".. it's manual either way.. removing the key is fine.. 
but there are two deletions - not one:
 
1. applications/cto-dev-kpr/templates/policy.yaml out of bdg-eng-tops-techops-argocd-pipeline -->  else the app-of-apps re-renders it;

2. the policy Application in ArgoCD — the app-of-apps runs prune: false, so removing the file alone won't clean it up         

 
I'm assuming that both are needed: policy and policy-sandbox share namespace "policy" and each has prune: true, so if both exist they delete each other's resources... 
 
Hold the bom-input merge... the sandbox chart published today still has placeholder :latest images that were never built — enabling it now takes Policy off cto-dev-kpr with nothing that can start. 
 
We have policy-service#465 and policy-console#266 open to fix that...

 
Monday, the order would be this (check if makes sense Patricia Batista Duarte Esteban Jose Herrera Vargas):

--> (1) merge #465 + #266 → development builds
https://github.com/kyndryl-cto/bdg-sw-plcy-policy-service/pull/465
https://github.com/kyndryl-cto/bdg-sw-plcy-policy-console/pull/266

--> (2) rebuild adapter-service + agentic-ai-poc
(will try to get these PR's prepared before Monday)

--> (3) check all 4 keys in policy-sandbox-master.json

--> (4) merge #226, then #971
https://github.com/kyndryl-cto/bdg-eng-tops-techops-bom-calculator/pull/226/changes
https://github.com/kyndryl-cto/bdg-eng-tops-techops-bom-input/pull/971

--> (5) delete policy.yaml + the ArgoCD app
 
--> (6) document all that, so we can replicate with KAIF (or any other app

--> (7) be happy! 
```
