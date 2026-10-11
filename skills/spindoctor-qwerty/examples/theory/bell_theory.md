# Bell-state correlation theory

**Claim.** H on qubit 0 followed by CNOT(0->1) creates the Bell state (|00> + |11>)/sqrt(2).

**Prediction.** Only outcomes `00` and `11` appear, each with probability 0.5; `01` and `10` never appear.
The fidelity with the ideal Bell state is 1.

```
q.circuit new bellth 2
q.circuit add h 0
q.circuit add cx 0 1
q.circuit run shots 4000 basis z
q.query fidelity state=[1/sqrt(2),0,0,1/sqrt(2)] convention=squared
```
