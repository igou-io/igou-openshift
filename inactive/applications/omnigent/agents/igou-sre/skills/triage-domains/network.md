# Network: MetalLB/BGP, OVN-K, Gateway API

1. MetalLB/BGP: `oc get pods -n metallb-system | grep -v Running`, then
   peer state from both ends — speaker logs
   (`oc logs -n metallb-system -l component=speaker --since 1h | grep -iE 'bgp|bfd'`)
   and the router (`routeros-ro <router> routing/bgp/session`, `-h` for
   syntax). VIPs are `autoAssign: false` pools SPLIT with rk8s — the
   router import-filters announcements on the wrong side; a "VIP not
   advertised" symptom right after a pool change is that filter.
2. Known failure mode: reachable VIP but deterministic ~7 s first-byte
   stall = asymmetric-return conntrack drop on the router (MetalLB accept
   rules must sit above `drop invalid` in the forward chain). Check the
   symptom-keyed page before re-deriving it.
3. OVN-K secondary networking: `oc get nncp` (all Available?), ovnkube
   pod health in openshift-ovn-kubernetes, and for localnet symptoms the
   OVS bridge needs `allow-extra-patch-ports: true` (nmstate NNCPs under
   clusters/ocp/nmstate/).
4. Gateway API tiers: shared per-tier Gateways in
   clusters/ocp/gateway-api/; guest-dmz serves *.dmz.igou.systems on a
   pinned VIP. Pinned VIPs (hermes-ssh, jellyfin, guest-dmz) are
   cross-repo contracts with router DNS/firewall in igou-inventory —
   a one-sided change IS the likely cause; name both files.
5. Blackbox probe alerts: the probe list lives in
   components/user-workload-monitoring/exporters/blackbox-exporter/;
   check whether the target or the prober moved.
