"""
MOF-FF parameters.
"""
#### BTW-FF atom types and properties #####
MOFFF_atoms = {
# FF_num  at_num  at_mass   valance vdW_rad[A]  epsilo[kcal/mol] H-bond  charge   atom_type  description
"5"   :(    1  ,    1.008  ,   1  , 1.50 , 0.020 , 0 ,  0.0 , 0.723638  ), # h     "h-benzene"
"2"   :(    6  ,   12.000  ,   3  , 1.960, 0.056 , 0 ,  0.0 , 1.162986  ), # c     "c-benzene"
"165" :(    29 ,    63.546 ,    5 , 2.26 , 0.296 , 0 ,  0.0 , 2.073266  ), # cu     "cu_paddle-wheel"
"167" :(    8  ,   15.999  ,   2  , 1.820, 0.059 , 0 ,  0.0 , 1.117553  ), # o     "o-carb"
"168" :(    6  ,   12.000  ,   3  , 1.940, 0.056 , 0 ,  0.0 , 1.162986  ) # c     "c-carb"
}
####   BONDs in BTW-FF ####
MOFFF_bonds = {
#FF_bond    k [kcal/mol/A^2]	r [A]
"2_2"     :(     7.080  ,   1.394  ,  0.0  ),
"2_5"     :(     5.430  ,   1.094  ,  0.0  ),
"165_165" :(     1.049  ,   2.536  ,  0.0  ),
"165_167" :(     1.464  ,   1.914  ,  50.0 ),  # morse potential term !!!!!!!!   50.0
"168_167" :(     8.140  ,   1.278  ,  0.0  ),
"2_168"   :(     5.013  ,   1.485  ,  0.0  )
}
#### ANGLES in BTW-FF ####
MOFFF_angles = {
# at1_atcen_at2     k[kcal/mol] Theta[degree]
"2_2_2"       :(     0.741   ,  127.05   ,  127.05  ,  127.05  ,  0.047 ,   0.047  ,   0.499 ),
"2_2_5"       :(     0.503   ,  120.35   ,  120.35  ,  120.35  , -0.175 ,   0.372  ,   0.649 ),
"165_167_168" :(     0.191   ,  126.814  ,  126.814 ,  126.814 ,  0.0   ,   0.0    ,   0.0   ),
"167_168_167" :(     1.544   ,  123.490  ,  123.490 ,  123.490 ,  0.023 ,   0.023  ,   0.099 ),
"165_165_167" :(     0.408   ,   84.336  ,   84.336 ,   84.336 ,  0.0   ,   0.0    ,   0.0   ),
"2_2_168"     :(     0.798   ,  117.711  ,  117.711 ,  117.711 ,  0.0   ,   0.0    ,   0.0   ),
"2_168_167"   :(     1.105   ,  115.098  ,  115.098 ,  115.098 ,  0.0   ,   0.0    ,   0.0   ),
#"167_165_167" :(     0.220   ,  180.0    ,    4     ,    1 .0  ,   1.0 ) # Fourier angle
}
#### DIHEDRALs in BTW-FF
MOFFF_dihedrals = {
# atom1_atom2_atom3_atom4 k_1[kcal/mol/rad^2] thetha1[degree] n1 k_2[kcal/mol/rad^2] thetha2[degree] n2 k_3[kcal/mol/rad^2] thetha3[degree] n3
"2_2_2_2"         :(    0.0 , 0.0 ,  1   ,  4.379 ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"5_2_2_5"         :(    0.0 , 0.0 ,  1   ,  5.972 ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"2_2_2_5"         :(    0.0 , 0.0 ,  1   ,  6.316 ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"167_165_167_168" :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"165_167_168_167" :(    0.0 , 0.0 ,  1   ,  4.528 ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"165_165_167_168" :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"167_165_165_167" :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.609 ,  180.0 ,  4 ),
"167_165_165_167" :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.609 ,  180.0 ,  4 ),
"168_2_2_5"       :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"168_2_2_2"       :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"2_2_168_167"     :(    0.0 , 0.0 ,  1   ,  1.741 ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 ),
"165_167_168_2"   :(    0.0 , 0.0 ,  1   ,  0.0   ,  180.0 ,  2 ,  0.0  ,  0.0 ,  3 ,  0.0   ,  180.0 ,  4 )
}
#### Out-of-Plane bending in BTW-FF
MOFFF_opbends = {
# atom1_atom2_atom3_atom4 K[kcal/mol/rad^2] theta[degree]
"2_2_5_2"      :(   0.019 , 180.0 ),
"2_2_2_5"      :(   0.019 , 180.0 ),
"5_2_2_2"      :(   0.019 , 180.0 ),
"2_2_168_2"    :(   0.087 , 180.0 ),
"2_2_2_168"    :(   0.087 , 180.0 ),
"2_168_167_167":(   0.19 , 180.0 ),
"167_168_167_2":(   0.190 , 180.0 ),
"167_168_2_167":(   0.190 , 180.0 ),
"168_2_2_2"    :(   0.087 , 180.0 ),


}
