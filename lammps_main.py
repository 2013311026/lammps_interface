#!/usr/bin/env python
"""
main.py

the program starts here.

"""

# Turn on keyword expansion to get revision numbers in version strings
# in .hg/hgrc put
# [extensions]
# keyword =
#
# [keyword]
# lammps_main.py =
#
# [keywordmaps]
# Revision = {rev}


try:
    __version_info__ = (0, 0, 0, int("$Revision$".strip("$Revision: ")))
except ValueError:
    __version_info__ = (0, 0, 0, 0)
__version__ = "%i.%i.%i.%i"%__version_info__

import sys
import math
from structure_data import CIF, Structure
from ForceFields import UFF, UserFF
from datetime import datetime

def construct_data_file(ff):

    t = datetime.today()
    string = "Created on %s\n\n"%t.strftime("%a %b %d %H:%M:%S %Y %Z")

    string += "%12i atoms\n"%(len(ff.structure.atoms))
    string += "%12i bonds\n"%(len(ff.structure.bonds))
    string += "%12i angles\n"%(len(ff.structure.angles))
    string += "%12i dihedrals\n"%(len(ff.structure.dihedrals))
    string += "%12i impropers\n\n"%(len(ff.structure.impropers))

    string += "%12i atom types\n"%(len(ff.unique_atom_types.keys()))
    string += "%12i bond types\n"%(len(ff.unique_bond_types.keys()))
    string += "%12i angle types\n"%(len(ff.unique_angle_types.keys()))
    string += "%12i dihedral types\n"%(len(ff.unique_dihedral_types.keys()))
    string += "%12i improper types\n"%(len(ff.unique_improper_types.keys()))

    cell = ff.structure.cell
    string += "%19.6f %10.6f %s %s\n"%(0., cell.lx, "xlo", "xhi")
    string += "%19.6f %10.6f %s %s\n"%(0., cell.ly, "ylo", "yhi")
    string += "%19.6f %10.6f %s %s\n"%(0., cell.lz, "zlo", "zhi")
    string += "%19.6f %10.6f %10.6f %s %s %s\n"%(cell.xy, cell.xz, cell.yz, "xy", "xz", "yz")


    # Let's track the forcefield potentials that haven't been calc'd or user specified
    no_bond = set()
    no_angle = set()
    no_dihedral = set()
    no_improper = set()


    string += "\nMasses\n\n"
    for key in sorted(ff.unique_atom_types.keys()):
        unq_atom = ff.unique_atom_types[key]
        mass, type = unq_atom.mass, unq_atom.force_field_type
        string += "%5i %8.4f # %s\n"%(key, mass, type)

    string += "\nBond Coeffs\n\n"
    for key in sorted(ff.unique_bond_types.keys()):
        bond = ff.unique_bond_types[key]
        #print bond.atoms[0].ff_type_index
        #print bond.atoms[1].ff_type_index
        if bond.function is None:
            no_bond.add(key)
        else:
            ff1, ff2 = bond.atoms[0].force_field_type, bond.atoms[1].force_field_type
            K = bond.parameters[0]
            R = bond.parameters[1]
            string += "%5i %s "%(key, bond.function)
            for i in range(0, len(bond.parameters)): string += "%15.6f "%(float(bond.parameters[i]))
            string += "# %s %s\n"%(ff1, ff2)


    string += "\nAngle Coeffs\n\n"
    for key in sorted(ff.unique_angle_types.keys()):
        angle = ff.unique_angle_types[key]
        atom_a, atom_b, atom_c = angle.atoms

        if angle.function is None:
            no_angle.add(key)
        else:
            string += "%5i %s "%(key, angle.function)
            for i in range(0, len(angle.parameters)): string += "%15.6f "%(float(angle.parameters[i]))
            string += "# %s %s %s\n"%(atom_a.force_field_type, atom_b.force_field_type, atom_c.force_field_type)
    

    string +=  "\nDihedral Coeffs\n\n"
    for key in sorted(ff.unique_dihedral_types.keys()):
        dihedral = ff.unique_dihedral_types[key]
        atom_a, atom_b, atom_c, atom_d = dihedral.atoms
        if dihedral.function is None:
            no_dihedral.add(key)
        else:
            string += "%5i %s "%(key, dihedral.function)
            for i in range(0, len(dihedral.parameters)): string += "%15.6f "%(float(dihedral.parameters[i]))
            string += "# %s %s %s %s\n"%(atom_a.force_field_type, atom_b.force_field_type, atom_c.force_field_type, atom_d.force_field_type)
    print string

	# Changed 1. to 1 because LAMMPS was parsing it as a float instead of an int
    string += "\nImproper Coeffs\n\n"
    for key in sorted(ff.unique_improper_types.keys()):
        improper = ff.unique_improper_types[key]
        atom_a, atom_b, atom_c, atom_d = improper.atoms  
        if improper.function is None:
            no_improper.add(key)
        else:
            string += "%5i %s "%(key, improper.function)
            print improper.parameters
            for i in range(0, len(improper.parameters)): string += "%15.6f "%(float(improper.parameters[i]))
            string += "# %s %s %s %s\n"%(atom_a.force_field_type, atom_b.force_field_type, atom_c.force_field_type, atom_d.force_field_type)


    #************[atoms]************
	# Added 1 to all atom, bond, angle, dihedral, improper indices (LAMMPS does not accept atom of index 0)
    string += "\nAtoms\n\n"
    for atom in ff.structure.atoms:
        molid = 444
        string += "%8i %8i %8i %11.5f %10.5f %10.5f %10.5f\n"%(atom.index+1, molid, atom.ff_type_index, atom.charge,
                                                       atom.coordinates[0], atom.coordinates[1], atom.coordinates[2])

    #************[bonds]************
    string += "\nBonds\n\n"
    for bond in ff.structure.bonds:
        atm1, atm2 = bond.atoms 
        type = bond.ff_type_index 
        string += "%8i %8i %8i %8i\n"%(bond.index+1, type, atm1.index+1, atm2.index+1)

    #************[angles]***********
    string += "\nAngles\n\n"
    for angle in ff.structure.angles:
        atm1, atm2, atm3 = angle.atoms 
        type = angle.ff_type_index
        # what order are they presented? b, a, c? or a, b, c?
        string += "%8i %8i %8i %8i %8i\n"%(angle.index+1, type, atm1.index+1, atm2.index+1, atm3.index+1)

    #************[dihedrals]********
    string += "\nDihedrals\n\n"
    for dihedral in ff.structure.dihedrals:
        atm1, atm2, atm3, atm4 = dihedral.atoms 
        type = dihedral.ff_type_index
        # order?
        string += "%8i %8i %8i %8i %8i %8i\n"%(dihedral.index+1, type, atm1.index+1, atm2.index+1,
                                               atm3.index+1, atm4.index+1)

    #************[impropers]********
    string += "\nImpropers\n\n"
    for improper in ff.structure.impropers:
        atm1, atm2, atm3, atm4 = improper.atoms
        type = improper.ff_type_index 
        # order?
        string += "%8i %8i %8i %8i %8i %8i\n"%(improper.index+1, type, atm1.index+1, 
                                                                       atm2.index+1,
                                                                       atm3.index+1,
                                                                       atm4.index+1)

    return string

def construct_input_file(ff):

    inp_str = ""
    inp_str += "%-15s %s\n"%("units","real")
    inp_str += "%-15s %s\n"%("atom_style","full")
    inp_str += "%-15s %s\n"%("boundary","p p p")
    inp_str += "%-15s %s\n"%("dielectric","1")
    inp_str += "\n"
    inp_str += "%-15s %s\n"%("pair_style", "hybrid lj/cut/coul/long 8.50000 11.5")
    inp_str += "%-15s %s\n"%("bond_style","harmonic")
    inp_str += "%-15s %s\n"%("angle_style","hybrid fourier fourier/simple")
    inp_str += "%-15s %s\n"%("dihedral_style","harmonic")
    inp_str += "%-15s %s\n"%("improper_style","fourier")
    inp_str += "%-15s %s\n"%("kspace_style","ewald 0.001") 
    inp_str += "\n"
    inp_str += "%-15s %s\n"%("box tilt","large")
    inp_str += "%-15s %s\n"%("read_data","data.%s"%(ff.structure.name))

    for (id1,id2), (eps, sig) in ff.unique_van_der_waals.items():
        # TODO(change eps to 0 for Al, Si, Ge)
        inp_str += "%-15s %6i %4i %s %24.15f %25.15f\n"%("pair_coeff", id1, id2, "lj/cut/coul/long", eps, sig)
    
    inp_str += "\n"
    inp_str += "%-15s %s\n"%("dump","%s_mov all xyz 1 %s_mov.xyz"%(ff.structure.name, ff.structure.name))
    inp_str += "%-15s %s\n"%("pair_modify","tail yes mix arithmetic")
    inp_str += "%-15s %s\n"%("fix","1 all box/relax tri 0.0 vmax 0.01")
    inp_str += "%-15s %s\n"%("min_style","cg")
    inp_str += "%-15s %s\n"%("minimize","1.0e-4 1.0e-6 10000 100000")

    return inp_str

def clean(name):
    if name.startswith('./run_x'):
        name = name[10:]
    if name.endswith('.cif'):
        name = name[:-4]
    elif name.endswith('.niss'):
        name = name[:-5]
    elif name.endswith('.out-CO2.csv'):
        name = name[:-12]
    elif name.endswith('-CO2.csv'):
        name = name[:-8]
    elif name.endswith('.flog'):
        name = name[:-5]
    elif name.endswith('.out.cif'):
        name = name[:-8]
    elif name.endswith('.tar'):
        name = name[:-4]
    elif name.endswith('.db'):
        name = name[:-3]
    elif name.endswith('.faplog'):
        name = name[:-7]
    elif name.endswith('.db.bak'):
        name = name[:-7]
    elif name.endswith('.csv'):
        name = name[:-4]
    elif name.endswith('.out'):
        name = name[:-4]
    return name

def main():
    print("Lammps_interface version: %s"%__version__)

    

    # TODO add commandline parsing options in the future
    # for now just read off the second command as the FF to choose

    cifname = sys.argv[1]
    mofname = clean(cifname)
    cif = CIF()
    # NB can add the filename as the second argument of the class instance,
    # or from a separate function

    if len(sys.argv) > 2:
        ffname = sys.argv[2]
    


    # set as the first argument for testing
    cif.read(cifname)

    struct = Structure(name=mofname)
    struct.from_CIF(cif)
    struct.compute_angles()
    struct.compute_dihedrals()
    struct.compute_improper_dihedrals()
    ff = UserFF(struct)
    ff.compute_force_field_terms()
    
    #ff = UFF(struct)
    #ff.compute_force_field_terms()
    data_str = construct_data_file(ff) 
    inp_str = construct_input_file(ff)
   
    datafile = open("data.%s"%struct.name, 'w')
    datafile.writelines(data_str)
    datafile.close()

    inpfile = open("in.%s"%struct.name, 'w')
    inpfile.writelines(inp_str)
    inpfile.close()
    
    print("files created!")

if __name__ == "__main__": 
    main()

