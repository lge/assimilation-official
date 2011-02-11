/**
@page SystemGoals System Goals

@section GreaterSystemGoals Greater Goals

- Make the system easy to install and a snap to configure: autoconfiguration and discovery are key.
  If it isn't easy to install and easy to use - it won't get used.
- The client agent software <i>must</i> run on Windows along with pretty much all POSIX-like machines.
- Make the system extremely scalable (tens of thousands of nodes) - it should be possible to perform basic system monitoring
  using a very small machine.  Cloud-scale environments should always be in view when designing and implementing.
  As much as possible, it should rely on O(1) techniques.  Some features (like collecting statistical data) are inherently O(N).
  But even so, there are methods of minimizing network traffic and so on to make this as inexpensive on the
  central system - and the client systems - as it can be.  This affects the packet format chosen.
- It should be able to use a variety of different monitoring agents - OCF agents, Nagios agents, etc.
- It should be easily extensible into controlling the same machines using these same mechanisms.
  Adding an LRM proxy (for example) should be planned on at the infrastructure level.
- Reusability.  It has proven worthwhile for the components which make sense to be independently usable - to be
  truly separable and usable without the rest of the infrastructure.
- I'm pretty sure I've forgotten some things - this list will grow over time...

@section LesserSystemGoals Sexy or otherwise good goals to consider
- Mobile clients - iPad, iPhone, Android all come to mind...
- Lifecycle management (update mechanisms) may show up as a GoodThing&tm; eventually...
*/
