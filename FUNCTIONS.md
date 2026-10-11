# SpinDoctor Qwerty 1.1.0 - function table

This is exactly what the `spindoctor_functions` tool shows in chat (SpinDoctor 3.1.2 parity). `spindoctor_functions` with `section=presets` lists all 241 presets.

## SpinDoctor Qwerty - plugin tools

| Function | What it does | Command to type |
|---|---|---|
| Function table (spindoctor_functions) | Show this table in chat | Ask: "show the SpinDoctor functions" (CLI: `spindoctor_cli.py functions`) |
| Run a script (spindoctor_run_script) | Run any q.* lines above; returns results + TXT/JSON/CSV/PDF report paths | Ask: "run q.circuit new bell 2 / q.circuit add h 0 / ..." |
| Run a preset (spindoctor_run_preset) | Run qc-001..qc-241 with overrides | Ask: "run preset qc-067 with shots=64" |
| List presets (spindoctor_list_presets) | Search the 241 presets | Ask: "list presets about Grover" |
| Read a report (spindoctor_report) | List/read TXT reports (PDF/JSON paths alongside) | Ask: "show the newest SpinDoctor report" |
| Test a theory from a file (spindoctor_test_theory source=file) | Read a .txt/.md/.pdf/.py/.json/.csv/.q attachment, then hypothesis -> prediction -> q.* script -> run -> verdict + TXT/PDF theory report | Ask: "test the theory in C:/notes/theory.md" (the host must pass the file path/content) |
| Test a theory from text (spindoctor_test_theory source=text) | Same pipeline for pasted text | Ask: "test this theory: a Hadamard on \|0> gives 50/50" |
| Test the theory we discussed (spindoctor_test_theory source=chat) | The AI summarises the theory from the conversation (claims, assumptions, variables, prediction), you confirm, then it is tested; quoted excerpts go in the report under 'Source: chat history'. An exported chat transcript (.txt/.md/.json/.html) also works | Ask: "test the theory we discussed" or "test the theory in my exported chat C:/chats/conversation.json" |

### Circuits (q.circuit) - build, run and inspect named circuits (1..298 logical qubits; one entangled factor <=59)

| Function | What it does | Command to type |
|---|---|---|
| q.circuit new | Create a named circuit with N logical qubits (1..298) and select it | `q.circuit new bell 2` |
| q.circuit new (wide) | Wide register (>29 qubits): prepared once, sampled jointly per factor, basis z only | `q.circuit new wide_demo 298` |
| q.circuit add mcx7 | Seven-control X: operands 0..6 control operand 7 | `q.circuit add mcx7 0 1 2 3 4 5 6 7` |
| q.circuit add | Append a gate: name, then angles, then qubit(s); `all` = every qubit | `q.circuit add h 0` |
| q.circuit add (2-qubit) | Append a controlled/two-qubit gate (control first) | `q.circuit add cx 0 1` |
| q.circuit input | Set the initial computational-basis state (index) | `q.circuit input 0` |
| q.circuit show | Show the selected circuit's gates and descriptor hash | `q.circuit show` |
| q.circuit run | Simulate and sample N shots in basis z, x or y (seeded Born sampling); registers wider than 29 qubits use basis z only | `q.circuit run shots 1000 basis z` |
| q.circuit status | Run/job status, memory plan and work counters | `q.circuit status` |
| q.circuit result | Full measurement histogram of the last run | `q.circuit result` |
| q.circuit state | Exact amplitude of one basis state of the last run | `q.circuit state 3` |
| q.circuit spin | Bloch (spin) vector of one qubit after the last run | `q.circuit spin 0` |
| q.circuit export | Export the circuit program as JSON | `q.circuit export` |
| q.circuit list | List saved circuits (owner, qubits, gates) | `q.circuit list` |
| q.circuit select | Select a saved circuit by name | `q.circuit select bell` |
| q.circuit preset | Load and run a built-in circuit: bell, ghz N, qft N [shots N] [basis x\|y\|z] [run=false] [as NAME] | `q.circuit preset ghz 5` |
| q.circuit clear | Remove every gate from the selected circuit | `q.circuit clear` |
| q.circuit delete | Delete a saved circuit | `q.circuit delete ghz-5` |
| q.circuit cancel | Cancel a running circuit job (no-op when it is finished) | `q.circuit cancel` |
| q.circuit memory | Set the circuit memory budget in MiB | `q.circuit memory 1024` |
| q.circuit memory auto | Set the budget from currently usable RAM (also q.tranche memory auto) | `q.circuit memory auto` |
| q.circuit capacity | Show or set how many circuits can be saved (1..1024) | `q.circuit capacity 64` |
| q.circuit prune | Delete preset-owned circuits, keeping the newest N | `q.circuit prune presets 0` |
| q.circuit help | List every q.circuit command | `q.circuit help` |

### Queries on the last circuit run (q.query) - first build and run a circuit, e.g. q.circuit new bell 2, add h 0, add cx 0 1, run shots 1000 basis z

| Function | What it does | Command to type |
|---|---|---|
| q.query amplitudes | List state-vector amplitudes | `q.query amplitudes max=16` |
| q.query probabilities | List basis probabilities | `q.query probabilities max=16` |
| q.query marginal | Marginal distribution of chosen qubits | `q.query marginal qubits=[0] basis=z` |
| q.query reduced-density | Reduced density matrix of chosen qubits | `q.query reduced-density qubits=[0]` |
| q.query purity | Purity Tr(rho^2) of a subsystem | `q.query purity qubits=[0]` |
| q.query entropy | Von Neumann entropy of a subsystem | `q.query entropy qubits=[0] base=2` |
| q.query expectation | Expectation value of a Pauli string | `q.query expectation pauli="Z0 Z1"` |
| q.query concurrence | Two-qubit concurrence (entanglement) | `q.query concurrence qubits=[0,1]` |
| q.query negativity | Negativity across a bipartition | `q.query negativity partition=[0] convention=trace-norm-minus-one-divided-by-two` |
| q.query stabilizers | Check candidate stabilizer generators | `q.query stabilizers generators=["X0 X1","Z0 Z1"]` |
| q.query fidelity | Fidelity of the output with a target state | `q.query fidelity state=[1/sqrt(2),0,0,1/sqrt(2)] convention=squared` |

### Tranche register (q.tranche) - one coherent register with sparse/dense factor blocks

| Function | What it does | Command to type |
|---|---|---|
| q.tranche prepare | Prepare an N-qubit register (zero or plus) | `q.tranche prepare 4 zero` |
| q.tranche gate | Apply a gate to the register | `q.tranche gate h 0` |
| q.tranche gate (2-qubit) | Apply an entangling gate (merges factor blocks) | `q.tranche gate cx 0 1` |
| q.tranche state | Exact amplitude of one basis state | `q.tranche state 0` |
| q.tranche spin | Bloch vector of one qubit | `q.tranche spin 0` |
| q.tranche measure | Sample a qubit (optional `collapse`) | `q.tranche measure 0 basis z shots 100` |
| q.tranche status | Factor blocks, memory and job status | `q.tranche status` |
| q.tranche memory | Set the register memory limit in MiB | `q.tranche memory 512` |
| q.tranche export | Export the register (factor amplitudes) as JSON | `q.tranche export` |
| q.tranche save | Write a dense checkpoint to the workspace | `q.tranche save dense` |
| q.tranche resume | Reload the saved checkpoint | `q.tranche resume` |
| q.tranche cancel | Cancel a running register job (no-op when finished) | `q.tranche cancel` |
| q.tranche reset | Reset the register to its prepared state | `q.tranche reset` |
| q.tranche release | Release the register and its memory | `q.tranche release` |
| q.tranche from | Bind a register to procedural-grid address A (needs q.prepare first) | `q.prepare grid 1000 1000` ⏎ `q.tranche from 0` |
| q.tranche help | List every q.tranche command | `q.tranche help` |

### Procedural product-state grid (q.prepare / q.gate / q.measure ...)

| Function | What it does | Command to type |
|---|---|---|
| q.prepare grid | Create the procedural grid of M x N product-state addresses | `q.prepare grid 1000 1000` |
| q.migrate | Rotate the field by time step t | `q.migrate t 1` |
| q.gate | Apply a single-qubit gate to every address (U, RY, RZ, H, X, Y, Z, S, T, I) | `q.gate h all` |
| q.state | Exact spinor at one address | `q.state 12345` |
| q.measure | Sample one address in a basis | `q.measure 12345 basis z shots 100` |
| q.verify rule | Prove the product rule symbolically | `q.verify rule` |
| q.verify samples | Cross-check N random addresses against the reference | `q.verify samples 256 errors-only` |
| q.verify status | Status of the last verification | `q.verify status` |
| q.verify cancel | Cancel a running verification (no-op when finished) | `q.verify cancel` |
| q.export descriptor | Export the grid descriptor (seeds hashed, gate log) | `q.export descriptor` |
| q.reset | Reset the grid (seeds and measurement counter kept) | `q.reset` |
| q.status | Whole-workspace status (grid, circuit, tranche, memory) | `q.status` |
| q.help | List the q.* namespaces and capabilities | `q.help` |

### Presets and sequences (q.preset / q.sequence)

| Function | What it does | Command to type |
|---|---|---|
| q.preset list | List all 241 presets | `q.preset list` |
| q.preset show | Show one preset's commands | `q.preset show qc-067` |
| q.preset run | Run a preset (optional name=value overrides) | `q.preset run qc-067 shots=64` |
| q.sequence status | Status of the last preset/sequence run | `q.sequence status` |
| q.sequence help | List sequence/preset commands | `q.sequence help` |

### Resource planning (q.resource)

| Function | What it does | Command to type |
|---|---|---|
| q.resource memory | Memory needed for an N-qubit state | `q.resource memory n=29 representation=statevector dtype=complex128 units=binary` |
| q.resource max-n | Largest N that fits in a memory budget | `q.resource max-n memory-mib=512 representation=statevector dtype=complex128 overhead-mib=0` |
| q.resource factor-memory | Memory for factor blocks of given sizes | `q.resource factor-memory block-sizes=[29] dtype=complex128` |
| q.resource tranche-plan | Plan tranches over many addresses | `q.resource tranche-plan addresses=500000000000000 width=29 semantics=independent-groups` |
| q.resource sampling | Sampling error for p and shots | `q.resource sampling probability=0.5 shots=1024 metric=standard-error` |
| q.resource shots | Shots needed for epsilon/delta | `q.resource shots epsilon=0.01 delta=0.05 bound=hoeffding-two-sided` |
| q.resource grover | Grover iteration estimate | `q.resource grover database-size=1048576 marked=1 formula=asymptotic` |
| q.resource qec | Physical qubits for an error-correction overhead | `q.resource qec logical-qubits=29 physical-per-logical=1000 model=user-supplied-overhead` |
| q.resource headroom | This machine's RAM headroom | `q.resource headroom` |
| q.resource auto | Auto memory plan from measured RAM | `q.resource auto` |

### Math calculators (q.math) - exact FP64 linear algebra on small states

| Function | What it does | Command to type |
|---|---|---|
| q.math normalize | Normalise an amplitude vector | `q.math normalize amplitudes=[1,i]` |
| q.math norm | Norm of a vector | `q.math norm amplitudes=[1/sqrt(3),sqrt(2/3)]` |
| q.math probabilities | Born probabilities of amplitudes | `q.math probabilities amplitudes=[sqrt(3)/2,i/2]` |
| q.math bloch | Bloch vector of a qubit state | `q.math bloch amplitudes=[1/sqrt(2),i/sqrt(2)]` |
| q.math from-bloch | State from Bloch angles | `q.math from-bloch theta=pi/3 phi=pi/4` |
| q.math validate-bloch | Check a Bloch vector is physical | `q.math validate-bloch x=0.2 y=0.3 z=0.4` |
| q.math density | Density matrix of a state | `q.math density amplitudes=[1/sqrt(2),i/sqrt(2)]` |
| q.math validate-density | Check a density matrix | `q.math validate-density rho=[[0.7,0],[0,0.3]]` |
| q.math purity | Purity of a density matrix | `q.math purity rho=[[0.7,0],[0,0.3]]` |
| q.math entropy | Von Neumann entropy | `q.math entropy rho=[[0.5,0],[0,0.5]] base=2` |
| q.math overlap | Inner product <a\|b> | `q.math overlap a=[1,0] b=[1/sqrt(2),1/sqrt(2)]` |
| q.math fidelity | State fidelity | `q.math fidelity a=[1/sqrt(2),1/sqrt(2)] b=[1/sqrt(2),-1/sqrt(2)] convention=squared` |
| q.math trace-distance | Trace distance of two density matrices | `q.math trace-distance rho=[[1,0],[0,0]] sigma=[[0,0],[0,1]]` |
| q.math gate-matrix | Matrix of a named gate | `q.math gate-matrix gate=h` |
| q.math compare-gates | Compare two gates (optionally up to phase) | `q.math compare-gates p=pi/3 rz=pi/3 up-to-global-phase=true` |
| q.math unitary | Check a matrix is unitary | `q.math unitary matrix=[[0,1],[1,0]] tolerance=1e-12` |
| q.math tensor | Tensor (Kronecker) product | `q.math tensor left=H right=I2` |
| q.math commutator | Commutator [A,B] | `q.math commutator a=X b=Z` |
| q.math eigen | Eigenvalues/vectors of an operator | `q.math eigen operator=X` |
| q.math expectation | <psi\|O\|psi> | `q.math expectation state=[sqrt(3)/2,1/2] operator=Z` |
| q.math canonical-phase | Remove global phase | `q.math canonical-phase amplitudes=[i/sqrt(2),-1/sqrt(2)] preserve-original=true` |

### Physics models (q.model)

| Function | What it does | Command to type |
|---|---|---|
| q.model spectrum | Spectrum of a Pauli Hamiltonian | `q.model spectrum hamiltonian="-1*Z0" n=1` |
| q.model ising | Ising energies/ground states | `q.model ising h=[0,0] J=[[0,-1],[-1,0]] energy="sum_i h_i s_i + sum_i<j J_ij s_i s_j" spins=plus-minus-one` |
| q.model qubo-to-ising | Convert QUBO to Ising | `q.model qubo-to-ising Q=[[1,-1],[-1,1]] objective="x_transpose_Q_x" mapping="x=(1-s)/2"` |
| q.model evolve | Time evolution under H | `q.model evolve n=1 initial=[1/sqrt(2),1/sqrt(2)] hamiltonian="0.5*Z0" time=pi/2 hbar=1` |
| q.model mbqc | Measurement-based teleport step | `q.model mbqc initial=[sqrt(3)/2,1/2] resource="one plus ancilla" entangler=CZ measurement="X on input" branch=all` |
| q.model compare | Compare computing models | `q.model compare models=[gate-based,closed-system-adiabatic,open-system-annealing]` |
| q.model compare-codes | Compare QEC code families | `q.model compare-codes families=[surface-code,qldpc] assumptions=[connectivity,decoder,noise-model,rate,distance]` |
| q.model topology | Explain topological (anyon) models | `q.model topology braid=example anyon-model=unspecified action=explain` |

### Lessons (q.lesson) - explained concepts

| Function | What it does | Command to type |
|---|---|---|
| q.lesson amplitude-vs-probability | Amplitude vs probability | `q.lesson amplitude-vs-probability example=[1/sqrt(2),i/sqrt(2)]` |
| q.lesson entanglement | Product vs entangled states | `q.lesson entanglement compare=["plus tensor plus","Bell phi plus"]` |
| q.lesson complexity | Complexity classes | `q.lesson complexity classes=[P,BPP,BQP,PSPACE,NP] distinguish=[proven,conjectured]` |
| q.lesson parallelism | What quantum parallelism is (not) | `q.lesson parallelism example=grover` |
| q.lesson stabilizer | Gottesman-Knill / stabilizer simulation | `q.lesson stabilizer assumptions=[stabilizer-input,clifford-gates,pauli-measurements]` |
| q.lesson magic | Magic states and non-Clifford resources | `q.lesson magic caveats=[input-dependent-T,qubit-Wigner-convention,nonclifford-not-sufficient-for-advantage]` |
| q.lesson algorithms | Shor vs Grover (toy scope) | `q.lesson algorithms compare=[shor,grover] scope=toy-calculator` |
| q.lesson pqc | Post-quantum cryptography standards | `q.lesson pqc standards=[FIPS203,FIPS204,FIPS205] mode=verify-current-primary-sources` |

### Noise (q.noise)

| Function | What it does | Command to type |
|---|---|---|
| q.noise apply | Apply a noise channel to a state | `q.noise apply state=[1,0] channel=bit-flip p=0.1` |
| q.noise circuit | Noisy circuit (density matrix) | `q.noise circuit n=2 input=0 gates="h 0;cx 0 1" channel=bit-flip p=0.1 targets=[0]` |
| q.noise t1 | Amplitude damping (T1) | `q.noise t1 excited-probability=1 time-us=20 t1-us=100` |
| q.noise t2 | Dephasing (T2) | `q.noise t2 coherence=0.5 time-us=20 t2-us=100` |
| q.noise readout | Readout-error correction | `q.noise readout probabilities=[0.75,0.25] confusion=[[0.98,0.03],[0.02,0.97]] orientation=rows-observed-columns-true` |
| q.noise zne | Zero-noise extrapolation | `q.noise zne scales=[1,2,3] expectations=[0.8,0.7,0.6] model=linear` |

### Error correction (q.qec)

| Function | What it does | Command to type |
|---|---|---|
| q.qec repetition3 | 3-qubit bit-flip code (encode/syndrome/simulate) | `q.qec repetition3 encode state=[1/sqrt(2),1/sqrt(2)]` |
| q.qec phase-repetition3 | 3-qubit phase-flip code | `q.qec phase-repetition3 simulate state=[1/sqrt(2),i/sqrt(2)] error=Z2 recover=true` |
| q.qec validate | Validate stabilizer generators | `q.qec validate stabilizers=["X0","Z0"]` |
| q.qec parameters | Code parameters [[n,k]] | `q.qec parameters n=7 independent-stabilizers=6` |
| q.qec correction-budget | Correctable errors for distance d | `q.qec correction-budget distance=5` |
| q.qec compare | Mitigation vs correction | `q.qec compare mitigation=zne correction=stabilizer-code` |

### Compilation (q.compile)

| Function | What it does | Command to type |
|---|---|---|
| q.compile identity | Check two gate lists are equivalent | `q.compile identity left="h 0;x 0;h 0" right="z 0" n=1 equivalence=exact` |
| q.compile simplify | Cancel/merge gates | `q.compile simplify n=1 gates="h 0;h 0;t 0;tdg 0;ry 0.2 0;ry -0.2 0" preserve-global-phase=true` |
| q.compile count | Gate counts | `q.compile count n=2 gates="h 0;t 0;cx 0 1;tdg 1" counting=logical` |
| q.compile depth | Circuit depth | `q.compile depth n=3 gates="h 0;h 1;cx 0 2;z 1" connectivity=all-to-all scheduling=earliest-dependencies` |
| q.compile classify | Clifford / non-Clifford classification | `q.compile classify n=2 gates="h 0;s 1;cx 0 1" input=computational-basis` |
| q.compile universality | Is a gate set universal? | `q.compile universality set=[h,t,cx] semantics=approximate` |

### Algorithms (q.algorithm)

| Function | What it does | Command to type |
|---|---|---|
| q.algorithm phase-estimation | Quantum phase estimation on a small unitary | `q.algorithm phase-estimation counting-qubits=3 unitary="p 2.356194490192345 3" eigenstate=[0,1] power-map="qj-controls-U^(2^j)" inverse-qft=include-final-swaps` |

### Inputs, folders, history and sequences (q.input / q.folder / q.history / q.sequence)

| Function | What it does | Command to type |
|---|---|---|
| q.input help | Attachment formats (.json .qasm .qasm2 .txt .circuit .csv .pdf), limits and every q.input command | `q.input help` |
| q.input add | Attach a local file (cartridge): `q.input add path="FILE"`; returns an ID and a preview. Nothing runs on upload | `q.input list` |
| q.input list | List attachments with format, parse status and SHA256 | `q.input list` |
| q.input show / export / delete ID | Preview, export or delete one attachment by its 32-character ID | `q.input list` |
| q.input table ID | Inspect a measurement CSV: columns, numeric counts, min/max/mean | `q.input help` |
| q.input fit ID target=COL features=[COL,...] | Empirical least-squares fit (QR) with equation, R^2, RMSE, residuals; in-sample only, no causality claimed | `q.input help` |
| q.input evaluate / import ID | Resolve parameters and validate (evaluate) or create the circuit (import); never runs it | `q.input help` |
| q.input run ID | Run an attachment's program or command list as one sequence (TXT/JSON/CSV/PDF reports per step) | `q.input help` |
| q.folder run path="/abs/folder" | Run every supported file in a folder in ordinal order (128 files, 4 MiB, 128 commands each); unsupported files are listed as skipped; first failure stops the job | `q.folder help` |
| q.folder status / cancel | Compact status of the last folder job (cartridge folder jobs finish synchronously) | `q.folder status` |
| q.history list / show ID / export ID | Browse the TXT/JSON/CSV/PDF archive of every command (needs a workspace with reports) | `q.history help` |
| q.sequence status / export [JOB_ID] / cancel | Last sequence job record; export a recent job by ID | `q.sequence status` |
| q.sequence help | Sequence rules (1..128 commands, barriers, reports) | `q.sequence help` |

### Cartridge (q.cartridge) - plugin-only

| Function | What it does | Command to type |
|---|---|---|
| q.cartridge info | Version, numeric backend, qubit cap and guardrails | `q.cartridge info` |

### Gate set (for q.circuit add / q.tranche gate; angles in radians, then qubits)

| Function | What it does | Command to type |
|---|---|---|
| gate h | Append gate h | `q.circuit add h 0` |
| gate x | Append gate x | `q.circuit add x 0` |
| gate y | Append gate y | `q.circuit add y 0` |
| gate z | Append gate z | `q.circuit add z 0` |
| gate s / sdg | Append gate s / sdg | `q.circuit add sdg 0` |
| gate t / tdg | Append gate t / tdg | `q.circuit add t 0` |
| gate i (id) | Append gate i (id) | `q.circuit add i 0` |
| gate sx / sxdg | Append gate sx / sxdg | `q.circuit add sx 0` |
| gate rx / ry / rz THETA | Append gate rx / ry / rz THETA | `q.circuit add ry 0.3 0` |
| gate p THETA (phase) | Append gate p THETA (phase) | `q.circuit add p 0.3 0` |
| gate u / u3 THETA PHI LAMBDA | Append gate u / u3 THETA PHI LAMBDA | `q.circuit add u 0.1 0.2 0.3 1` |
| gate cx (cnot) / cy / cz / ch | Append gate cx (cnot) / cy / cz / ch | `q.circuit add cz 0 1` |
| gate swap | Append gate swap | `q.circuit add swap 0 1` |
| gate cp / crx / cry / crz THETA | Append gate cp / crx / cry / crz THETA | `q.circuit add crz 0.2 0 1` |
| gate rxx / ryy / rzz / rzx THETA | Append gate rxx / ryy / rzz / rzx THETA | `q.circuit add rzz 0.2 0 1` |
| gate cu THETA PHI LAMBDA GAMMA | Append gate cu THETA PHI LAMBDA GAMMA | `q.circuit add cu 0.1 0.2 0.3 0.4 0 1` |
| gate ccx (toffoli) | Append gate ccx (toffoli) | `q.circuit add ccx 0 1 2` |
| gate cswap (fredkin) | Append gate cswap (fredkin) | `q.circuit add cswap 0 1 2` |

### Not available in this plugin (SpinDoctor 3.1.2 desktop only, or not implemented anywhere)

| Function | Why / alternative |
|---|---|
| `q.compile synthesize` | Not implemented in SpinDoctor 3.1.2 either (needs a validated Clifford+T synthesizer); preset qc-198 reports it as unavailable |
| `GPU/OpenCL verification` | The cartridge compares the CPU rule with an independent CPU reference instead of an OpenCL GPU |
| `Desktop GUI, drag-and-drop uploads, background jobs` | Use q.input add path=..., q.folder run path=... (synchronous) and spindoctor_report |

_Classical FP64 simulation: up to 298 logical qubits per register, at most 59 qubits in one entangled factor, and this Python port refuses dense factors above its memory guard (22 qubits stdlib / 26 with NumPy). Not a quantum computer; no quantum-advantage claims._
