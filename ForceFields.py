from uff import UFF_DATA
from structure_data import Structure, Atom, Bond, Angle, Dihedral
import math
from operator import mul
import itertools
import abc
DEG2RAD = math.pi/180.

class ForceField(object):

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def bond_term(self):
        """Computes the bond parameters"""

    @abc.abstractmethod
    def angle_term(self):
        """Computes the angle parameters"""

    @abc.abstractmethod
    def dihedral_term(self):
        """Computes the dihedral parameters"""

    @abc.abstractmethod
    def improper_term(self):
        """Computes the improper dihedral parameters"""
    
    @abc.abstractmethod
    def unique_atoms(self):
        """Computes the number of unique atoms in the structure"""
    
    @abc.abstractmethod
    def unique_bonds(self):
        """Computes the number of unique bonds in the structure"""
    

class UFF(ForceField):
    
    def __init__(self, struct):
        self.structure = struct

        self.unique_atom_types = {}
        self.unique_bond_types = {}
        self.unique_angle_types = {}
        self.unique_dihedral_types = {}
        self.unique_improper_types = {}
        self.unique_van_der_waals = {}

    def bond_term(self, bond):
        """Harmonic assumed"""
        atom1, atom2 = bond.atoms
        fflabel1, fflabel2 = atom1.force_field_type, atom2.force_field_type
        r_1 = UFF_DATA[fflabel1][0]
        r_2 = UFF_DATA[fflabel2][0]
        chi_1 = UFF_DATA[fflabel1][8]
        chi_2 = UFF_DATA[fflabel2][8]

        rbo = -0.1332*(r_1 + r_2)*math.log(bond.order)
        ren = r_1*r_2*(((math.sqrt(chi_1) - math.sqrt(chi_2))**2))/(chi_1*r_1 + chi_2*r_2)
        r0 = (r_1 + r_2 + rbo - ren)
        K = 664.12*(UFF_DATA[fflabel1][5]*UFF_DATA[fflabel2][5])/(r0**3)
        bond.function = 'harmonic'
        bond.parameters = (K, r0)

    def angle_term(self, angle):
        """several cases exist where the type of atom in a particular environment is considered
        in both the parameters and the functional form of the term.


        A small cosine fourier expansion in (theta)
        E_0 = K_{IJK} * {sum^{m}_{n=0}}C_{n} * cos(n*theta)

        Linear, trigonal-planar, square-planar, and octahedral:
        two-term expansion of the above equation, n=0 as well as
        n=1, n=3, n=4, and n=4 for the above geometries.
        E_0 = K_{IJK}/n^2 * [1 - cos(n*theta)]

        in Lammps, the angle syle called 'fourier/simple' can be used
        to describe this functional form.
        
        general non-linear case:
        three-term Fourier expansion
        E_0 = K_{IJK} * [C_0 + C_1*cos(theta) + C_2*cos(2*theta)]
        
        in Lammps, the angle style called 'fourier' can be used to
        describe this functional form.

        Both 'fourier/simple' and 'fourier' are available from the 
        USER_MISC package in Lammps, so be sure to compile Lammps with
        this package.

        """

        # fourier/simple
        sf = ['linear', 'trigonal-planar', 'square-planar', 'octahedral']
        angle_type = self.uff_angle_type(angle)
        a_atom, b_atom, c_atom = angle.atoms
        ab_bond, bc_bond = angle.bonds

        auff, buff, cuff = a_atom.force_field_type, b_atom.force_field_type, c_atom.force_field_type

        theta0 = UFF_DATA[buff][1]
        cosT0 = math.cos(theta0*DEG2RAD)
        sinT0 = math.cos(theta0*DEG2RAD)

        c2 = 1.0 / (4.0*sinT0*sinT0)
        c1 = -4.0 * c2 * cosT0
        c0 = c2 * (2.0*cosT0*cosT0 + 1.0)

        za = UFF_DATA[auff][5]
        zc = UFF_DATA[cuff][5]
        
        r_ab = ab_bond.parameters[1]
        r_bc = bc_bond.parameters[1]
        r_ac = math.sqrt(r_ab*r_ab + r_bc*r_bc - 2.*r_ab*r_bc*cosT0)

        beta = 664.12/r_ab/r_bc
        ka = beta*(za*zc /(r_ac**5.))
        ka *= (3.*r_ab*r_bc*(1. - cosT0*cosT0) - r_ac*r_ac*cosT0)

        if angle_type in sf:
            angle.function = 'fourier/simple' 
            if angle_type == 'linear' or angle_type == 'trigonal-planar':
                kappa = ka
                c0 = -1.
                c1 = 1.

            if angle_type == 'trigonal-planar':
                kappa = ka/9.
                c0 = -1.
                c1 = 3.

            if angle_type == 'square-planar' or angle_type == 'octahedral':
                kappa = ka/16.
                c0 = -1.
                c1 = 4.

        # general-nonlinear
            angle.parameters = (kappa, c0, c1)
        else:
            angle.function = 'fourier'

            #TODO: a bunch of special cases which require molecular recognition here..
            # water, for example has it's own theta0 angle.

            theta0 = UFF_DATA[buff][1]

            c2 = 1. / (4.*math.sin(theta0)*math.sin(theta0))
            c1 = -4.*c2*math.cos(theta0)
            c0 = c2*(2.*math.cos(theta0)*math.cos(theta0) + 1)
            kappa = ka
            angle.parameters = (kappa, c0, c1, c2)

    def uff_angle_type(self, angle):
        l, c, r = angle.atoms
        """ determined by the central atom type """
        bent_types = ['O_3', 'S_3', 'O_R', 'N_2']
        name = angle.b_atom.force_field_type
        if len(c.neighbours) == 2:
            if name[:3] in bent_types:
                return 'bent'
            return 'linear'

        trig_types = ['C_R', 'C_2', 'O_3_z', 'O_3']
        if len(c.neighbours) == 3:
            if name in trig_types:
                return 'trigonal-planar'
            return 'trigonal-pyramidal'

        # Need flag for Zn4O type MOFs where Zn is tetrahedral.
        # vs. Zn paddlewheel where Zn is square planar.
        sqpl_types = ['Fe6+2', 'Zn3+2', 'Cu3+1']
        if len(c.neighbours) == 4:
            if name in sqpl_types:
                return 'square-planar'
            return 'tetrahedral'

        if len(c.neighbours) == 6:
            return 'octahedral'

    def dihedral_term(self, dihedral):
        """Use a small cosine Fourier expansion

        E_phi = 1/2*V_phi * [1 - cos(n*phi0)*cos(n*phi)]

        this is available in Lammps as the harmonic potential
        """
        atom_a = dihedral.a_atom
        atom_b = dihedral.b_atom
        atom_c = dihedral.c_atom
        atom_d = dihedral.d_atom

        torsiontype = dihedral.bc_bond.order
        coord_bc = (len(atom_b.neighbours), len(atom_c.neighbours))
        bc = (atom_b.force_field_type, atom_c.force_field_type)
        M = mul(*coord_bc)
        V = 0
        n = 0
        #FIXME(pboyd): coord = (4, x) in cases probably copper paddlewheel
        sp2_types = ['O_2', 'O_R', 'C_2', 'C_R', 'N_R', 'N_2', 'S_2', 'S_R']
        sp3_types = ['O_3', 'O_3_z', 'O_3_M', 'C_3', 'N_3', 'P_3+3', 'P_3+5', 
                     'P_3+q', 'S_3+2', 'S_3+4', 'S_3+6', 'B_3']

        mixed_case = (bc[0] in sp2_types and bc[1] in sp3_types) or \
                (bc[0] in sp3_types and bc[1] in sp2_types)
        all_sp2 = (bc[0] in sp2_types and bc[1] in sp2_types)
        all_sp3 = (bc[0] in sp3_types and bc[1] in sp3_types)

        phi0 = 0
        if all_sp3:
            phi0 = 60.0
            n = 3
            vi = UFF_DATA[atom_b.force_field_type][6]
            vj = UFF_DATA[atom_c.force_field_type][6]
            
            if atom_b.atomic_number == 8:
                vi = 2.
                n = 2
                phi0 = 90.
            elif atom_b.atomic_number in (16, 34, 52, 84):
                vi = 6.8
                n = 2
                phi0 = 90.0
            if atom_c.atomic_number == 8:
                vj = 2.
                n = 2
                phi0 = 90.0

            elif atom_c.atomic_number in (16, 34, 52, 84):
                vj = 6.8
                n = 2
                phi0 = 90.0

            V = (vi*vj)**0.5 # CHECK UNITS!!!!

        elif all_sp2: 
            ui = UFF_DATA[atom_b.force_field_type][7]
            uj = UFF_DATA[atom_c.force_field_type][7]
            phi0 = 180.0
            n = 2
            V = 5.0 * (ui*uj)**0.5 * (1. + 4.18*math.log(torsiontype))

        elif mixed_case: 
            phi0 = 180.0
            n = 3
            V = 2.  # CHECK UNITS!!!!
            
            if bc[1] in sp3_types:
                if atom_c.atomic_number in (8, 16, 34, 52):
                    n = 2
                    phi0 = 90.
            elif bc[0] in sp3_types:
                if atom_b.atomic_number in (8, 16, 34, 52):
                    n = 2
                    phi0 = 90.0
            # special case group 6 elements
            if n==2: 
                ui = UFF_DATA[atom_b.force_field_type][7]
                uj = UFF_DATA[atom_c.force_field_type][7]
                V = 5.0 * (ui*uj)**0.5 * (1. + 4.18*math.log(torsiontype))

        V /= float(M)
        nphi0 = n*phi0

        if abs(math.sin(nphi0*DEG2RAD)) > 1.0e-3:
            print("WARNING!!! nphi0 = %r" % nphi0)

        else:
            phi_s = nphi0 - 180.0

        dihedral.function = 'harmonic'
        dihedral.parameters = (0.5*V, math.cos(nphi0*DEG2RAD), n)

    def improper_term(self, improper):

        atom_a, atom_b, atom_c, atom_d = improper.atoms
        if atom_b.force_field_type in ('N_3', 'N_2', 'N_R', 'O_2', 'O_R'):
            c0 = 1.0
            c1 = -1.0
            c2 = 0.0
            koop = 6.0 
        elif atom_b.force_field_type in ('P_3+3', 'As3+3', 'Sb3+3', 'Bi3+3'):
            if atom_b.force_field_type == 'P_3+3':
                phi = 84.4339 * DEG2RAD
            elif atom_b.force_field_type == 'As3+3':
                phi = 86.9735 * DEG2RAD
            elif atom_b.force_field_type == 'Sb3+3':
                phi = 87.7047 * DEG2RAD
            else:
                phi = 90.0 * DEG2RAD
            c1 = -4.0 * math.cos(phi)
            c2 = 1.0
            c0 = -1.0*c1*math.cos(phi) + c2*math.cos(2.0*phi)
            koop = 22.0 
        elif atom_b.force_field_type in ('C_2', 'C_R'):
            c0 = 1.0
            c1 = -1.0
            c2 = 0.0
            koop = 6.0 
            if 'O_2' in (atom_a.force_field_type, atom_c.force_field_type, atom_d.force_field_type):
                koop = 50.0 
        else:
            return 

        koop /= 3

        improper.function = "fourier"
        improper.parameters = (koop, c0, c1, c2)

    def unique_atoms(self):
        # ff_type keeps track of the unique integer index
        ff_type = {}
        count = 0
        for atom in self.structure.atoms:
            
            if atom.force_field_type is None:
                label = atom.element
            else:
                label = atom.force_field_type

            try:
                type = ff_type[label]
            except KeyError:
                count += 1
                type = count
                ff_type[label] = type  
                self.unique_atom_types[type] = atom 

            atom.ff_type_index = type

    def unique_bonds(self):
        count = 0
        bb_type = {}
        for bond in self.structure.bonds:
            idx1, idx2 = bond.indices
            atm1, atm2 = self.structure.atoms[idx1], self.structure.atoms[idx2]
            
            self.bond_term(bond)        
            try:
                type = bb_type[(atm1.ff_type_index, atm2.ff_type_index, bond.order)]
            except KeyError:
                try:
                    type = bb_type[(atm2.ff_type_index, atm1.ff_type_index, bond.order)]
                except KeyError:
                    count += 1
                    type = count
                    bb_type[(atm1.ff_type_index, atm2.ff_type_index, bond.order)] = type

                    self.unique_bond_types[type] = bond 
            bond.ff_type_index = type

    def unique_angles(self):
        ang_type = {}
        count = 0
        for angle in self.structure.angles:
            atom_a, atom_b, atom_c = angle.atoms
            type_a, type_b, type_c = atom_a.ff_type_index, atom_b.ff_type_index, atom_c.ff_type_index
            # compute and store angle terms
            self.angle_term(angle)

            try:
                type = ang_type[(type_a, type_b, type_c)]

            except KeyError:
                try:
                    type = ang_type[(type_c, type_b, type_a)]
                
                except KeyError:
                    count += 1
                    type = count
                    ang_type[(type_a, type_b, type_c)] = type
                    self.unique_angle_types[type] = angle 
            angle.ff_type_index = type


    def unique_dihedrals(self):
        count = 0
        dihedral_type = {}
        for dihedral in self.structure.dihedrals:
            atom_a, atom_b, atom_c, atom_d = dihedral.atoms
            type_a, type_b, type_c, type_d = (atom_a.ff_type_index,
                                              atom_b.ff_type_index,
                                              atom_c.ff_type_index,
                                              atom_d.ff_type_index)
            M = len(atom_c.neighbours)*len(atom_b.neighbours)
            try:
                type = dihedral_type[(type_a, type_b, type_c, type_d, M)]
            except KeyError:
                try:
                    type = dihedral_type[(type_d, type_c, type_b, type_a, M)]
                except KeyError:
                    count += 1
                    type = count
                    dihedral_type[(type_a, type_b, type_c, type_d, M)] = type
                    self.dihedral_term(dihedral)
                    self.unique_dihedral_types[type] = dihedral 
            dihedral.ff_type_index = type

    def unique_impropers(self):
        """How many times to list the same set of atoms ???"""
        count = 0
        improper_type = {}
        for improper in self.structure.impropers:
            atom_a, atom_b, atom_c, atom_d = improper.atoms
            type_a, type_b, type_c, type_d = (atom_a.ff_type_index, atom_b.ff_type_index,
                                              atom_c.ff_type_index, atom_d.ff_type_index)
            d1 = (type_b, type_a, type_c, type_d)
            d2 = (type_b, type_a, type_d, type_c)
            d3 = (type_b, type_c, type_d, type_a)
            d4 = (type_b, type_c, type_a, type_d)
            d5 = (type_b, type_d, type_a, type_c)
            d6 = (type_b, type_d, type_c, type_a)

            if d1 in improper_type.keys():
                type = improper_type[d1]
            elif d2 in improper_type.keys():
                type = improper_type[d2]
            elif d3 in improper_type.keys():
                type = improper_type[d3]
            elif d4 in improper_type.keys():
                type = improper_type[d4]
            elif d5 in improper_type.keys():
                type = improper_type[d5]
            elif d6 in improper_type.keys():
                type = improper_type[d6]
            else:
                count += 1
                type = count
                improper_type[d1] = type
                self.improper_term(improper)
                self.unique_improper_types[type] = improper

            improper.ff_type_index = type

    def van_der_waals_pairs(self):
        atom_types = self.unique_atom_types.keys()
        for type1, type2 in itertools.combinations_with_replacement(atom_types, 2):
            atm1 = self.unique_atom_types[type1]
            atm2 = self.unique_atom_types[type2]
            eps1 = UFF_DATA[atm1.force_field_type][3]
            eps2 = UFF_DATA[atm2.force_field_type][3]
            
            # radius --> sigma = radius*2**(-1/6)
            sig1 = UFF_DATA[atm1.force_field_type][2]*(2**(-1./6.))
            sig2 = UFF_DATA[atm2.force_field_type][2]*(2**(-1./6.))

            # l-b mixing
            eps = math.sqrt(eps1*eps2)
            sig = (sig1 + sig2) / 2.
            self.unique_van_der_waals[(type1, type2)] = (eps, sig)

    def compute_force_field_terms(self):
        self.unique_atoms()
        self.unique_bonds()
        self.unique_angles()
        self.unique_dihedrals()
        self.unique_impropers()
        self.van_der_waals_pairs()
