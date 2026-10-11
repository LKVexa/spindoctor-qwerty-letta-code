# Theory: |+> measured in the X basis always gives 0
q.circuit new plusx 1
q.circuit add h 0
q.circuit run shots 500 basis x
