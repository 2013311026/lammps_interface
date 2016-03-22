#!/usr/bin/env python
import os
import numpy as np
from scipy.spatial import distance
import math
import shlex
from CIFIO import CIF
from atomic import METALS
from copy import copy
from mof_sbus import InorganicCluster
from copy import deepcopy
import itertools

try:
    import networkx as nx
except ImportError:
    print("Warning: could not load networkx module, this is needed to produce the lammps data file.")
    sys.exit()
from collections import OrderedDict
from atomic import MASS, ATOMIC_NUMBER, COVALENT_RADII
from ccdc import CCDC_BOND_ORDERS
DEG2RAD=np.pi/180.

class MolecularGraph(nx.Graph):
    """Class to contain all information relating a structure file
    to a fully described classical system.
    Important specific arguments for atomic nodes:
    - mass
    - force_field_type
    - charge
    - cartesian_coordinates
    - description {contains all information about electronic environment
                   to make a decision on the final force_field_type}
        -hybridization [sp3, sp2, sp, aromatic]
    
    Important arguments for bond edges:
    - weight = 1
    - length
    - image_flag
    - force_field_type
    """
    node_dict_factory = OrderedDict
    def __init__(self, **kwargs):
        nx.Graph.__init__(self, **kwargs)
        # coordinates and distances will be kept in a matrix because 
        # networkx edge and node lookup is slow.
        try:
            self.name = kwargs['name']
        except KeyError:
            self.name = 'default'
        self.coordinates = None
        self.distance_matrix = None
        self.original_size = 0
        #TODO(pboyd): networkx edges do not store the nodes in order!
        # Have to keep a dictionary lookup to make sure the nodes 
        # are referenced properly (particularly across periodic images)
        self.sorted_edge_dict = {}
        self.molecule_images = []

    def edges_iter2(self, **kwargs):
        for n1, n2, d in self.edges_iter(**kwargs):
            yield (self.sorted_edge_dict[(n1, n2)][0], self.sorted_edge_dict[(n1,n2)][1], d)

    def add_atomic_node(self, **kwargs):
        """Insert nodes into the graph from the cif file"""
        #update keywords with more atom info
        # rename this to something more intuitive
        element = kwargs.pop('_atom_site_type_symbol')
        # replacing Atom.__init__
        kwargs.update({'mass':MASS[element]})
        kwargs.update({'element':element})
        kwargs.update({'cycle':False})
        kwargs.update({'rings':[]})
        kwargs.update({'atomic_number':ATOMIC_NUMBER.index(element)})
        kwargs.update({'pair_potential':None})
        kwargs.update({'h_bond_donor':False})
        kwargs.update({'h_bond_potential':None})
        try:
            kwargs['charge'] = float(kwargs['_atom_type_partial_charge'])
        except KeyError:
            kwargs['charge'] = 0.0
        try:
            fftype = kwargs.pop('_atom_site_description')
        except KeyError:
            fftype = None

        kwargs.update({'force_field_type':fftype})
        idx = self.number_of_nodes() + 1
        kwargs.update({'index':idx})
        #TODO(pboyd) should have some error checking here..
        n = kwargs.pop('_atom_site_label')
        kwargs.update({'ciflabel':n})
        # to identify Cu paddlewheels, etc.
        kwargs.update({'special_flag':None})
        self.add_node(idx, **kwargs)
   
    def compute_bonding(self, cell, scale_factor = 0.9):
        """Computes bonds between atoms based on covalent radii."""
        # here assume bonds exist, populate data with lengths and 
        # symflags if needed.
        if (self.number_of_edges() > 0):
            # bonding found in cif file
            sf = []
            for n1, n2, data in self.edges_iter2(data=True):
                # get data['ciflabel'] for self.node[n1] and self.node[n2]
                # update the sorted_edge_dict with the indices, not the 
                # cif labels
                n1data = self.node[n1]
                n2data = self.node[n2]
                n1label = n1data['ciflabel']
                n2label = n2data['ciflabel']
                try:
                    nn1, nn2 = self.sorted_edge_dict.pop((n1label, n2label))
                    if nn2 == n1label:
                        nn1 = n2
                        nn2 = n1
                    self.sorted_edge_dict.update({(n1, n2):(nn1, nn2)})
                    self.sorted_edge_dict.update({(n2, n1):(nn1, nn2)})
                except KeyError:
                    pass
                try:
                    nn1, nn2 = self.sorted_edge_dict.pop((n2label, n1label))
                    if nn2 == n1label:
                        nn1 = n2
                        nn2 = n1
                    self.sorted_edge_dict.update({(n2, n1):(nn1, nn2)})
                    self.sorted_edge_dict.update({(n1, n2):(nn1, nn2)})
                except KeyError:
                    pass

                sf.append(data['symflag'])
                bl = data['length']
                if bl <= 0.01:
                    id1, id2 = self.node[n1]['index']-1, self.node[n2]['index']-1
                    dist = self.distance_matrix[id1,id2]
                    data['length'] = dist

            if (set(sf) == set(['.'])):
                # compute sym flags
                for n1, n2, data in self.edges_iter2(data=True):
                    flag = self.compute_bond_image_flag(n1, n2, cell)
                    data['symflag'] = flag
            return

        # Here we will determine bonding from all atom pairs using 
        # covalent radii.
        for n1, n2 in itertools.combinations(self.nodes(), 2):
            node1, node2 = self.node[n1], self.node[n2]
            e1, e2 = node1['element'],\
                    node2['element']
            i1,i2 = node1['index']-1, node2['index']-1
            rad = (COVALENT_RADII[e1] + COVALENT_RADII[e2])
            dist = self.distance_matrix[i1,i2]
            if dist*scale_factor < rad:
                flag = self.compute_bond_image_flag(n1, n2, cell)
                self.sorted_edge_dict.update({(n1,n2): (n1, n2), (n2, n1):(n1, n2)})
                self.add_edge(n1, n2, key=self.number_of_edges() + 1, 
                              order=1.0, 
                              weight=1,
                              length=dist,
                              symflag = flag,
                              potential = None
                              )
    #TODO(pboyd) update this
    def compute_bond_image_flag(self, n1, n2, cell):
        """Update bonds to contain bond type, distances, and min img
        shift."""
        supercells = np.array(list(itertools.product((-1, 0, 1), repeat=3)))
        unit_repr = np.array([5,5,5], dtype=int)
        atom1 = self.node[n1]
        atom2 = self.node[n2]
        coord1 = self.coordinates[atom1['index']-1]
        coord2 = self.coordinates[atom2['index']-1]
        fcoords = np.dot(cell.inverse, coord2) + supercells
        
        coords = np.array([np.dot(j, cell.cell) for j in fcoords])
        
        dists = distance.cdist([coord1], coords)
        dists = dists[0].tolist()
        image = dists.index(min(dists))
        dist = min(dists)
        sym = '.' if all([i==0 for i in supercells[image]]) else \
                "1_%i%i%i"%(tuple(np.array(supercells[image],dtype=int) +
                                  unit_repr))
        return sym

    def add_bond_edge(self, **kwargs):
        """Add bond edges (weight factor = 1)"""
        #TODO(pboyd) should figure out if there are other cif keywords to identify
        # atom types
        #TODO(pboyd) this is .cif specific and should be contained within the cif 
        # file reading portion of the code. This is so that other file formats
        # can eventually be adopted if need be.

        n1 = kwargs.pop('_geom_bond_atom_site_label_1')
        n2 = kwargs.pop('_geom_bond_atom_site_label_2')
        try:
            length = float(kwargs.pop('_geom_bond_distance'))
        except KeyError:
            length = 0.0

        try:
            order = CCDC_BOND_ORDERS[kwargs['_ccdc_geom_bond_type']]
        except KeyError:
            order = 1.0

        try:
            flag = kwargs.pop('_geom_bond_site_symmetry_2')
        except KeyError:
            # assume bond does not straddle a periodic boundary
            flag = '.'
        kwargs.update({'length':length})
        kwargs.update({'weight': 1})
        kwargs.update({'order': order})
        kwargs.update({'symflag': flag})
        kwargs.update({'potential': None})
        # get the node index to avoid headaches
        for k,data in self.nodes_iter(data=True):
            if data['ciflabel'] == n1:
                n1 = k
            elif data['ciflabel'] == n2:
                n2 =k

        self.sorted_edge_dict.update({(n1,n2): (n1, n2), (n2, n1):(n1, n2)})
        self.add_edge(n1, n2, key=self.number_of_edges()+1, **kwargs)

    def compute_cartesian_coordinates(self, cell):
        """Compute the cartesian coordinates for each atom node"""
        coord_keys = ['_atom_site_x', '_atom_site_y', '_atom_site_z']
        fcoord_keys = ['_atom_site_fract_x', '_atom_site_fract_y', '_atom_site_fract_z']
        self.coordinates = np.empty((self.number_of_nodes(), 3))
        for node, data in self.nodes_iter(data=True):
            #TODO(pboyd) probably need more error checking..
            try:
                coordinates = np.array([float(data[i]) for i in coord_keys])
            except KeyError:
                coordinates = np.array([float(data[i]) for i in fcoord_keys])
                coordinates = np.dot(coordinates, cell.cell)
            data.update({'cartesian_coordinates':coordinates})

            self.coordinates[data['index']-1] = coordinates

    def compute_min_img_distances(self, cell):
        self.distance_matrix = np.empty((self.number_of_nodes(), self.number_of_nodes()))
        for n1, n2 in itertools.combinations(self.nodes(), 2):
            id1, id2 = self.node[n1]['index']-1,\
                                self.node[n2]['index']-1
            coords1, coords2 = self.coordinates[id1], self.coordinates[id2]
            try:
                dist = self.min_img_distance(coords1, coords2, cell)
            except TypeError:
                sys.exit()
            self.distance_matrix[id1][id2] = dist
            self.distance_matrix[id2][id1] = dist
    
    def min_img_distance(self, coords1, coords2, cell):
        one = np.dot(cell.inverse, coords1) % 1
        two = np.dot(cell.inverse, coords2) % 1
        three = np.around(one - two)
        four = np.dot(one - two - three, cell.cell)
        return np.linalg.norm(four)

    def compute_init_typing(self):
        """Find possible rings in the structure and 
        initialize the hybridization for each atom.
        More refined determinations of atom and bond types
        is computed below in compute_bond_typing

        """
        #TODO(pboyd) return if atoms already 'typed' in the .cif file
        # compute and store cycles
        cycles = []
        for node, data in self.nodes_iter(data=True):
            for n in self.neighbors(node):
                # fastest way I could think of..
                edge = self[node][n].copy()
                self.remove_edge(node, n)
                cycle = []
                try:
                    cycle = list(nx.all_shortest_paths(self, node, n))
                except nx.exception.NetworkXNoPath:
                    pass
                self.add_edge(node, n, **edge)
                #FIXME MW edit to only store cycles < len(10)
                # should be a harmless edit but maybe need to test
                if(len(cycle) <= 10):
                    cycles += cycle

        for label, data in self.nodes_iter(data=True):
            # N O C S
            neighbours = self.neighbors(label)
            element = data['element']
            if element == "C":
                if len(neighbours) >= 4:
                    self.node[label].update({'hybridization':'sp3'})
                elif len(neighbours) == 3:
                    self.node[label].update({'hybridization':'sp2'})
                elif len(neighbours) <= 2:
                    self.node[label].update({'hybridization':'sp'})
            elif element == "N":
                if len(neighbours) >= 3:
                    self.node[label].update({'hybridization':'sp3'})
                elif len(neighbours) == 2:
                    self.node[label].update({'hybridization':'sp2'})
                elif len(neighbours) == 1:
                    self.node[label].update({'hybridization':'sp'})
            elif element == "O":
                if len(neighbours) >= 2:
                    self.node[label].update({'hybridization':'sp3'})
                elif len(neighbours) == 1:
                    self.node[label].update({'hybridization':'sp2'})
            elif element == "S":
                if len(neighbours) == 2:
                    self.node[label].update({'hybridization':'sp3'})
                elif len(neighbours) == 1:
                    self.node[label].update({'hybridization':'sp2'})

            else:
                #default sp3
                self.node[label].update({'hybridization':'sp3'})
        # convert to aromatic
        # probably not a good test for aromaticity..
        arom = set(["C", "N", "O", "S"])
        for cycle in cycles:
            elements = [self.node[k]['element'] for k in cycle]
            neigh = [self.degree(k) for k in cycle]
            if np.all(np.array(neigh) <= 3) and set(elements) <= arom:
                for a in cycle:
                    self.node[a]['hybridization'] = 'aromatic'
                    self.node[a]['cycle'] = True
                    self.node[a]['rings'].append(cycle)

    def compute_bond_typing(self):
        """ Compute bond types and atom types based on the local edge
        environment.
        Messy, loads of 'ifs'
        is there a better way to catch chemical features?
        """ 
        #TODO(pboyd) return if bonds already 'typed' in the .cif file
        organic = set(["H", "C", "N", "O", "S"])
        for n1, n2, data in self.edges_iter2(data=True):
            elements = [self.node[a]['element'] for a in (n1,n2)]
            hybridization = [self.node[a]['hybridization'] for a in (n1, n2)]
            rings = [self.node[a]['rings'] for a in (n1, n2)]
            samering = False
            if set(hybridization) == set(['aromatic']):
                for r in rings[0]:
                    if n2 in r:
                        samering = True
                if(samering):
                    data.update({"order" : 1.5})

            if set(elements) == set(["C", "O"]):
                car = n1 if self.node[n1]['element'] == "C" else n2
                car_data = self.node[car]
                oxy = n2 if self.node[n2]['element'] == "O" else n1
                oxy_data = self.node[oxy]

                carnn = [i for i in self.neighbors(car) if i != oxy]
                try:
                    carnelem = [self.node[j]['element'] for j in carnn]
                except:
                    carnelem = []

                oxynn = [i for i in self.neighbors(oxy) if i != car]
                try:
                    oxynelem = [self.node[j]['element'] for j in oxynn]
                except:
                    oxynelem = []
                if "O" in carnelem:
                    at = carnn[carnelem.index("O")]
                    at_data = self.node[at]
                    if self.degree(at) == 1:
                        if self.degree(oxy) == 1:
                            #CO2
                            car_data['hybridization'] = 'sp'
                            oxy_data['hybridization'] = 'sp2'
                            data['order'] = 2.
                        else:
                            # ester
                            if set(oxynelem) <= organic:
                                car_data['hybridization'] = 'sp2'
                                oxy_data['hybridization'] = 'sp2'
                                data['order'] = 1 # this is the ether part of an ester... 
                            #carboxylate?
                            else:
                                car_data['hybridization'] = 'aromatic'
                                oxy_data['hybridization']= 'aromatic'
                                data['order'] = 1.5

                    else:
                        atnelem = [self.node[k]['element'] for k in self.neighbors(at)]
                        if (set(atnelem) <= organic):
                            # ester
                            if len(oxynn) == 0:
                                car_data['hybridization'] = 'sp2'
                                oxy_data['hybridization'] = 'sp2'
                                data['order'] = 2. # carbonyl part of ester
                            # some kind of resonance structure?
                            else:
                                car_data['hybridization'] = 'aromatic'
                                oxy_data['hybridization'] = 'aromatic'
                                data['order'] = 1.5
                        else:
                            car_data['hybridization'] = 'aromatic'
                            oxy_data['hybridization'] = 'aromatic'
                            data['order'] = 1.5
                if "N" in carnelem:
                    at = carnn[carnelem.index("N")]
                    # C=O of amide group
                    if self.degree(oxy) == 1:
                        data['order'] = 1.5
                        car_data['hybridization'] = 'aromatic'
                        oxy_data['hybridization'] = 'aromatic'
                # only one carbon oxygen connection.. could be C=O, R-C-O-R, R-C=O-R
                if (not "O" in carnelem) and (not "N" in carnelem):
                    if len(oxynn) > 0:
                        # ether
                        oxy_data['hybridization'] = 'sp3'
                        data['order'] = 1.0
                    else:
                        if car_data['cycle'] and car_data['hybridization'] == 'aromatic':
                            oxy_data['hybridization'] = 'aromatic'
                            data['order'] = 1.5
                        # carbonyl
                        else:
                            oxy_data['hybridization'] = 'sp2'
                            data['order'] = 2.0
            if set(elements) == set(["C", "N"]) and not samering:
                car = n1 if self.node[n1]['element'] == "C" else n2
                car_data = self.node[car]
                nit = n2 if self.node[n2]['element'] == "N" else n1
                nit_data = self.node[nit]
                carnn = [j for j in self.neighbors(car) if j != nit]
                carnelem = [self.node[k]['element'] for k in carnn]
                nitnn = [j for j in self.neighbors(nit) if j != car]
                nitnelem = [self.node[k]['element'] for k in nitnn]
                # aromatic amine connected -- assume part of delocalized system
                if car_data['hybridization'] == 'aromatic' and set(['H']) == set(nitnelem):
                    data['order'] = 1.5
                    nit_data['hybridization'] = 'aromatic'
                # amide?
                elif len(self.neighbors(car)) == 3 and len(nitnn) >=2:
                    if "O" in carnelem:
                        data['order'] = 1.5 # (amide)
                        nit_data['hybridization'] = 'aromatic'
            if (not self.node[n1]['cycle']) and (not self.node[n2]['cycle']) and (set(elements) <= organic):
                if set(hybridization) == set(['sp2']):
                    # check bond length.. probably not a good indicator..
                    try:
                        cr1 = COVALENT_RADII['%s_2'%elements[0]]
                    except KeyError:
                        cr1 = COVALENT_RADII[elements[0]]
                    try:
                        cr2 = COVALENT_RADII['%s_2'%(elements[1])]
                    except KeyError:
                        cr2 = COVALENT_RADII[elements[1]]
                    covrad = cr1 + cr2
                    if (data['length'] <= covrad*.95):
                        data['order'] = 2.0
                elif set(hybridization) == set(['sp']):
                    try:
                        cr1 = COVALENT_RADII['%s_1'%elements[0]]
                    except KeyError:
                        cr1 = COVALENT_RADII[elements[0]]
                    try:
                        cr2 = COVALENT_RADII['%s_1'%elements[1]]
                    except KeyError:
                        cr2 = COVALENT_RADII[elements[1]]
                    covrad = cr1 + cr2 
                    if (data['length'] <= covrad*.95):
                        data['order'] = 3.0

    def atomic_node_sanity_check(self):
        """Check for specific keyword/value pairs. Exit if non-existent"""

    def compute_angles(self):
        """angles are attached to specific nodes, this way
        if a node is cut out of a graph, the angle comes with it.

               
               b-----a
              /
             /
            c
               
        Must be updated with different adjacent nodes if a
        supercell is requested, and the angle crosses a 
        periodic image.
        
        """
        for b, data in self.nodes_iter(data=True):
            if self.degree(b) < 2:
                continue
            angles = itertools.combinations(self.neighbors(b), 2)
            for (a, c) in angles:
                data.setdefault('angles', {}).update({(a,c):{'potential':None}})
    
    def compute_dihedrals(self):
        """Dihedrals are attached to specific edges in the graph.
           a
            \ 
             b -- c
                   \ 
                    d

        the edge between b and c will contain all possible dihedral
        angles between the neighbours of b and c (this includes a
        and d and other possible bonded atoms)

        """
        for b, c, data in self.edges_iter2(data=True):
            b_neighbours = [k for k in self.neighbors(b) if k != c]
            c_neighbours = [k for k in self.neighbors(c) if k != b]
            for a in b_neighbours:
                for d in c_neighbours:
                    data.setdefault('dihedrals',{}).update({(a, d):{'potential':None}})
    
    def compute_improper_dihedrals(self):
        """Improper Dihedrals are attached to specific nodes in the graph.
           a
            \ 
             b -- c
             |     
             d    

        the node b will contain all possible improper dihedral 
        angles between the neighbours of b 

        """
        for b, data in self.nodes_iter(data=True):
            if self.degree(b) != 3:
                continue
            # three improper torsion angles about each atom
            local_impropers = list(itertools.permutations(self.neighbors(b)))
            for idx in range(0, 6, 2):
                (a, c, d) = local_impropers[idx]
                data.setdefault('impropers',{}).update({(a,c,d):{'potential':None}})

    def compute_topology_information(self, cell):
        self.compute_cartesian_coordinates(cell)
        self.compute_min_img_distances(cell)
        self.compute_bonding(cell)
        self.compute_init_typing()
        self.compute_bond_typing()
        self.detect_inorganic_clusters(num_neighbors=5) # num neighbors determines how many nodes from the metal element to cut out for comparison 
        self.compute_angles()
        self.compute_dihedrals()
        self.compute_improper_dihedrals()

    def sorted_node_list(self):
        return [n[1] for n in sorted([(data['index'], node) for node, data in self.nodes_iter(data=True)])]

    def sorted_edge_list(self): 
        return [e[1] for e in sorted([(data['index'], (n1, n2)) for n1, n2, data in self.edges_iter2(data=True)])]

    def show(self):
        nx.draw(self)

    def img_offset(self, cells, cell, maxcell, flag):
        unit_repr = np.array([5, 5, 5], dtype=int)
        if(flag == '.'):
            return cells.index(tuple([tuple([i]) for i in cell]))
        ocell = cell + np.array([int(j) for j in flag[2:]]) - unit_repr
        # get the image cell of this bond
        imgcell = ocell % maxcell
        # determine the atom indices from the image cell
        return cells.index(tuple([tuple([i]) for i in imgcell]))

    def update_symflag(self, cell, symflag, mincell, maxcell):
        unit_repr = np.array([5, 5, 5], dtype=int)
        ocell = cell + np.array([int(j) for j in symflag[2:]]) - unit_repr
        imgcell = ocell % maxcell
        if any(ocell < mincell) or any(ocell >= maxcell):
            newflaga = np.array([5,5,5])
            newflaga[np.where(ocell >= maxcell)] = 6
            newflaga[np.where(ocell < np.zeros(3))] = 4
            newflag = "1_%i%i%i"%(tuple(newflaga))
          
        else:
            newflag = '.'
        return newflag
    
    def correspondence_graph(self, graph, node_subset=None, tol=0.1):
        """Generate a correspondence graph between the nodes
        and the SBU.
        tolerance is the distance tolerance for the edge generation 
        in the correspondence graph.

        """
        if node_subset is None:
            node_subset = self.nodes()
        graph_nodes = graph.nodes()
        cg = nx.Graph()
        # add nodes to cg 
        for (i, j) in itertools.product(node_subset, graph_nodes):
            # match element-wise
            if self.node[i]['element'] == graph.node[j]['element']:
                cg.add_node((i,j))
        # add edges to cg
        for (a1, b1), (a2, b2) in itertools.combinations(cg.nodes(), 2):
            da = self.distance_matrix[a1-1, a2-1]
            db = graph.distance_matrix[b1-1, b2-1]
            if np.allclose(da, db, atol=tol):
                cg.add_edge((a1,b1), (a2,b2))
        return cg

    def detect_inorganic_clusters(self, num_neighbors=5):
        """Detect clusters such as the copper paddlewheel using
        maximum clique detection. This will assign specific atoms
        with a special flag for use when building their force field.


        """
        print("Detecting Inorganic clusters")
        metal_nodes = []
        for node, data in self.nodes_iter(data=True):
            if data['atomic_number'] in METALS:
                metal_nodes.append(node)

        no_cluster = []
        while metal_nodes:
            node = metal_nodes.pop() 
            data = self.node[node]
            try:
                possible_clusters = InorganicCluster[data['element']]
                neighbour_nodes = [] 
                instanced_neighbours = self.neighbors(node)
                # tree-like spanning of original node
                for j in range(num_neighbors):
                    temp_neighbours = []
                    for n in instanced_neighbours:
                        neighbour_nodes.append(n)
                        temp_neighbours += [j for j in self.neighbors(n) if j not in neighbour_nodes]
                    instanced_neighbours = temp_neighbours
                for n in neighbour_nodes:
                    try:
                        metal_nodes.pop(metal_nodes.index(n))
                    except:
                        pass
                cluster_found = False
                for name, cluster in possible_clusters.items():
                    cg = self.correspondence_graph(cluster, node_subset=neighbour_nodes + [node])
                    cliques = nx.find_cliques(cg)
                    for clique in cliques:
                        if len(clique) == cluster.number_of_nodes():
                            # found cluster
                            # update the 'hybridization' data
                            for i,j in clique:
                                self.node[i]['special_flag'] = cluster.node[j]['special_flag']
                            cluster_found = True
                            print("Found %s"%(name))
                            break

                    if(cluster_found):
                        break
                if not (cluster_found):
                    no_cluster.append(data['element'])
            except KeyError:
                # no recognizable metal clusters for element
                no_cluster.append(data['element'])

        for j in set(no_cluster):
            print ("No recognizable metal clusters for element %s"%(j))

    def build_supercell(self, sc, lattice, track_molecule=False):
        """Construct a graph with nodes supporting the size of the 
        supercell (sc)
        Oh man.. so ugly.        
        NB: this replaces and overwrites the original unit cell data 
            with a supercell. There may be a better way to do this 
            if one needs to keep both the super- and unit cells.
        """
        # preserve indices across molecules.
        unitatomlen = self.original_size
        totatomlen = nx.number_of_nodes(self)
        # keep a numerical index of the nodes.. this is to make sure that the molecules
        # are kept in their positions in the supercell (if replicated)
        unit_node_ids = sorted(self.nodes())
        origincell = np.array([0., 0., 0.])
        cells = list(itertools.product(*[itertools.product(range(j)) for j in sc]))
        maxcell = np.array(sc)
        rem_edges = []
        add_edges = []
        union_graphs = []
        orig_copy = deepcopy(self)
        for count, cell in enumerate(cells):
            newcell = np.array(cell).flatten()
            offset = count * unitatomlen 
            cartesian_offset = np.dot(newcell, lattice.cell) 
            if (count == 0):
                graph_image = self
            else:
                # rename nodes
                graph_image = nx.relabel_nodes(deepcopy(orig_copy), {unit_node_ids[i-1]: offset+unit_node_ids[i-1] for i in range(1, totatomlen+1)})
                graph_image.sorted_edge_dict = self.sorted_edge_dict.copy()
                for k,v in list(graph_image.sorted_edge_dict.items()):
                    newkey = (k[0] + offset, k[1] + offset) 
                    newval = (v[0] + offset, v[1] + offset)
                    del graph_image.sorted_edge_dict[k]
                    graph_image.sorted_edge_dict.update({newkey:newval})

            for i in range(1, totatomlen+1):
                graph_image.node[unit_node_ids[i-1]+offset]['image'] = unit_node_ids[i-1]

            if track_molecule:
                self.molecule_images.append(graph_image.nodes())
            # update cartesian coordinates for each node in the image
            for node, data in graph_image.nodes_iter(data=True):
                n_orig = data['image']
                data['cartesian_coordinates'] = data['cartesian_coordinates'] + cartesian_offset
                # update all angle and improper terms to the curent image indices. Dihedrals will be done in the edge loop
                # angle check
                try:
                    for (a, c), val in list(data['angles'].items()):

                        aid, cid = offset + a, offset + c
                        e_ba = graph_image[node][aid]
                        e_bc = graph_image[node][cid]
                        ba_symflag = e_ba['symflag']
                        order_ba = graph_image.sorted_edge_dict[(aid, node)]
                        if order_ba != (node, aid) and e_ba['symflag'] != '.':
                            ba_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in e_ba['symflag'][2:]])))
                        bc_symflag = e_bc['symflag']
                        order_bc = graph_image.sorted_edge_dict[(node, cid)]
                        if order_bc != (node, cid) and e_bc['symflag'] != '.':
                            bc_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in e_bc['symflag'][2:]]))) 
                        os_a = self.img_offset(cells, newcell, maxcell, ba_symflag) * unitatomlen
                        os_b = self.img_offset(cells, newcell, maxcell, bc_symflag) * unitatomlen
                        data['angles'].pop((a,c))
                        data['angles'][(a + os_a, c + os_b)] = val

                except KeyError:
                    # no angles for n1
                    pass
                # improper check
                try:
                    for (a, c, d), val in list(data['impropers'].items()):
                        aid, cid, did = offset + a, offset + c, offset + d
                        e_ba = graph_image[node][aid]
                        order_ba = graph_image.sorted_edge_dict[(node, aid)]
                        ba_symflag = e_ba['symflag']
                        e_bc = graph_image[node][cid]
                        order_bc = graph_image.sorted_edge_dict[(node, cid)]
                        bc_symflag = e_bc['symflag']
                        e_bd = graph_image[node][did]
                        order_bd = graph_image.sorted_edge_dict[(node, did)]
                        bd_symflag = e_bd['symflag']
                        if order_ba != (node, aid) and e_ba['symflag'] != '.':
                            ba_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in e_ba['symflag'][2:]])))
                        if order_bc != (node, cid) and e_bc['symflag'] != '.':
                            bc_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in e_bc['symflag'][2:]])))
                        if order_bd != (node, did) and e_bd['symflag'] != '.':
                            bd_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in e_bd['symflag'][2:]])))

                        os_a = self.img_offset(cells, newcell, maxcell, ba_symflag) * unitatomlen
                        os_c = self.img_offset(cells, newcell, maxcell, bc_symflag) * unitatomlen
                        os_d = self.img_offset(cells, newcell, maxcell, bd_symflag) * unitatomlen
                        data['impropers'].pop((a,c,d))
                        data['impropers'][(a + os_a, c + os_c, d + os_d)] = val

                except KeyError:
                    # no impropers for n1
                    pass
            
            # update nodes and edges to account for bonding to periodic images.
            for n1, n2, data in graph_image.edges_iter2(data=True):
                # flag boundary crossings, and determine updated nodes.
                # check symmetry flags if they need to be updated,
                n1_data = graph_image.node[n1]
                n2_data = graph_image.node[n2]
                try:
                    n1_orig = n1_data['image']
                    n2_orig = n2_data['image']
                except KeyError:
                    n1_orig = n1
                    n2_orig = n2
                # TODO(pboyd) the data of 'rings' for each node is not updated, do so if needed..
                # update angle, dihedral, improper indices.
                # dihedrals are difficult if the edge spans one of the terminal atoms..

                if (data['symflag'] != '.'):
                    os_id = self.img_offset(cells, newcell, maxcell, data['symflag']) 
                    offset_c = os_id * unitatomlen
                    img_n2 = offset_c + n2_orig
                    # pain...
                    opposite_flag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in data['symflag'][2:]]))) 
                    rev_n1_img = self.img_offset(cells, newcell, maxcell, opposite_flag) * unitatomlen + n1_orig 
                    # dihedral check
                    try:
                        for (a, d), val in list(data['dihedrals'].items()):
                            # check to make sure edge between a, n1 is not crossing an image
                            edge_n1_a = orig_copy[n1_orig][a]
                            order_n1_a = graph_image.sorted_edge_dict[(n1, a+offset)]
                            n1a_symflag = edge_n1_a['symflag']

                            edge_n2_d = orig_copy[n2_orig][d]
                            order_n2_d = graph_image.sorted_edge_dict[(n2, d+offset)]
                            n2d_symflag = edge_n2_d['symflag']

                            offset_a = offset
                            if order_n1_a != (n1, a+offset) and edge_n1_a['symflag'] != '.':
                                n1a_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in edge_n1_a['symflag'][2:]])))
                            if (edge_n1_a['symflag'] != '.'):
                                offset_a = self.img_offset(cells, newcell, maxcell, n1a_symflag) * unitatomlen
                            # check to make sure edge between n2, c is not crossing an image
                            offset_d = offset_c

                            if order_n2_d != (n2, d+offset) and edge_n2_d['symflag'] != '.':
                                n2d_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in edge_n2_d['symflag'][2:]])))
                            if (edge_n2_d['symflag'] != '.'):
                                offset_d = self.img_offset(cells, np.array(cells[os_id]).flatten(), maxcell, n2d_symflag) * unitatomlen

                            aid, did = offset_a + a, offset_d + d
                            copyover = data['dihedrals'].pop((a,d))
                            data['dihedrals'][(aid, did)] = copyover
                    except KeyError:
                        # no dihedrals here.
                        pass

                    # Update symmetry flag of bond
                    data['symflag'] = self.update_symflag(newcell, data['symflag'], origincell, maxcell)
                    add_edges += [((n1, img_n2),data)]
                    rem_edges += [(n1, n2)]
                else:
                    # dihedral check
                    try:
                        for (a, d), val in list(data['dihedrals'].items()):
                            # check to make sure edge between a, n1 is not crossing an image
                            edge_n1_a = orig_copy[n1_orig][a] 
                            order_n1_a = graph_image.sorted_edge_dict[(n1, a+offset)]
                            n1a_symflag = edge_n1_a['symflag']

                            edge_n2_d = orig_copy[n2_orig][d]
                            order_n2_d = graph_image.sorted_edge_dict[(n2, d+offset)]
                            n2d_symflag = edge_n2_d['symflag']

                            offset_a = offset
                            if order_n1_a != (n1, a+offset) and edge_n1_a['symflag'] != '.':
                                n1a_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in edge_n1_a['symflag'][2:]])))
                            if (edge_n1_a['symflag'] != '.'):
                                offset_a = self.img_offset(cells, newcell, maxcell, n1a_symflag) * unitatomlen
                            # check to make sure edge between n2, c is not crossing an image
                            offset_d = offset

                            if order_n2_d != (n2, d+offset) and edge_n2_d['symflag'] != '.':
                                n2d_symflag = "1_%i%i%i"%(tuple(np.array([10,10,10]) - np.array([int(j) for j in edge_n2_d['symflag'][2:]])))
                            if (edge_n2_d['symflag'] != '.'):
                                offset_d = self.img_offset(cells, newcell, maxcell, n2d_symflag) * unitatomlen

                            aid, did = offset_a + a, offset_d + d
                            copyover = data['dihedrals'].pop((a,d))
                            data['dihedrals'][(aid, did)] = copyover
                    except KeyError:
                        # no dihedrals here.
                        pass
            if (count > 0):
                union_graphs.append(graph_image)
        for G in union_graphs:
            for node, data in G.nodes_iter(data=True):
                self.add_node(node, **data)
           #once nodes are added, add edges.
        for G in union_graphs:
            self.sorted_edge_dict.update(G.sorted_edge_dict)
            for (n1, n2, data) in G.edges_iter2(data=True):
                self.add_edge(n1, n2, **data)

        for (n1, n2) in rem_edges:
            self.remove_edge(n1, n2)
            self.sorted_edge_dict.pop((n1,n2))
            self.sorted_edge_dict.pop((n2,n1))
        for (n1, n2), data in add_edges:
            self.add_edge(n1, n2, **data)
            self.sorted_edge_dict.update({(n1,n2):(n1,n2)})
            self.sorted_edge_dict.update({(n2,n1):(n1,n2)})

    def unwrap_node_coordinates(self, cell):
        """Must be done before supercell generation.
        This is a recursive method iterating over all edges.
        The design is totally unpythonic and 
        written in about 5 mins.. so be nice (PB)
        
        """
        supercells = np.array(list(itertools.product((-1, 0, 1), repeat=3)))
        # just use the first node as the unwrapping point..
        # probably a better way to do this to keep most atoms in the unit cell,
        # but I don't think it matters too much.
        nodelist = self.nodes()
        n1 = nodelist[0] 
        queue = []
        while (nodelist or queue):
            for n2, data in self[n1].items():
                if n2 not in queue and n2 in nodelist:
                    queue.append(n2)
                    coord1 = self.node[n1]['cartesian_coordinates'] 
                    coord2 = self.node[n2]['cartesian_coordinates']
                    fcoords = np.dot(cell.inverse, coord2) + supercells
                    
                    coords = np.array([np.dot(j, cell.cell) for j in fcoords])
                    
                    dists = distance.cdist([coord1], coords)
                    dists = dists[0].tolist()
                    image = dists.index(min(dists))
                    self.node[n2]['cartesian_coordinates'] += np.dot(supercells[image], cell.cell)
                    data['symflag'] = '.'
            del nodelist[nodelist.index(n1)]
            try:
                n1 = queue[0]
                queue = queue[1:]

            except IndexError:
                pass

    def store_original_size(self):
        self.original_size = self.number_of_nodes()

    def __iadd__(self, newgraph):
        self.sorted_edge_dict.update(newgraph.sorted_edge_dict)
        for n, data in newgraph.nodes_iter(data=True):
            self.add_node(n, **data)
        for n1,n2, data in newgraph.edges_iter2(data=True):
            self.add_edge(n1,n2, **data)
        return self

    def __or__(self, graph):
        cg = self.correspondence_graph(graph, tol=0.4)
        cliques = list(nx.find_cliques(cg))
        cliques.sort(key=len)
        return cliques[-1] 

def from_CIF(cifname):
    """Reads the structure data from the CIF
    - currently does not read the symmetry of the cell
    - does not unpack the assymetric unit (assumes P1)
    - assumes that the appropriate keys are in the cifobj (no error checking)
    """

    cifobj = CIF()
    cifobj.read(cifname)

    data = cifobj._data
    # obtain atoms and cell
    cell = Cell()
    # add data to molecular graph (to be parsed later..)
    mg = MolecularGraph(name=clean(cifname))
    cellparams = [float(i) for i in [data['_cell_length_a'], 
                                     data['_cell_length_b'], 
                                     data['_cell_length_c'],
                                     data['_cell_angle_alpha'], 
                                     data['_cell_angle_beta'], 
                                     data['_cell_angle_gamma']]]
    cell.set_params(cellparams)
    
    #add atom nodes
    id = cifobj.block_order.index('atoms')
    atheads = cifobj._headings[id]
    for atom_data in zip(*[data[i] for i in atheads]):
        kwargs = {a:j.strip() for a, j in zip(atheads, atom_data)}
        mg.add_atomic_node(**kwargs)

    # add bond edges, if they exist
    try:
        id = cifobj.block_order.index('bonds')
        bondheads = cifobj._headings[id]
        for bond_data in zip(*[data[i] for i in bondheads]):
            kwargs = {a:j.strip() for a, j in zip(bondheads, bond_data)}
            mg.add_bond_edge(**kwargs)
    except:
        # catch no bonds
        print("No bonds reported in cif file - computing bonding..")
    mg.store_original_size()
    return cell, mg

def write_CIF(graph, cell):
    """Currently used for debugging purposes"""
    c = CIF(name="%s.debug"%graph.name)
    # data block
    c.add_data("data", data_=graph.name)
    c.add_data("data", _audit_creation_date=
                        CIF.label(c.get_time()))
    c.add_data("data", _audit_creation_method=
                        CIF.label("Lammps Interface v.%s"%(str(0))))

    # sym block
    c.add_data("sym", _symmetry_space_group_name_H_M=
                        CIF.label("P1"))
    c.add_data("sym", _symmetry_Int_Tables_number=
                        CIF.label("1"))
    c.add_data("sym", _symmetry_cell_setting=
                        CIF.label("triclinic"))

    # sym loop block
    c.add_data("sym_loop", _symmetry_equiv_pos_as_xyz=
                        CIF.label("'x, y, z'"))

    # cell block
    c.add_data("cell", _cell_length_a=CIF.cell_length_a(cell.a))
    c.add_data("cell", _cell_length_b=CIF.cell_length_b(cell.b))
    c.add_data("cell", _cell_length_c=CIF.cell_length_c(cell.c))
    c.add_data("cell", _cell_angle_alpha=CIF.cell_angle_alpha(cell.alpha))
    c.add_data("cell", _cell_angle_beta=CIF.cell_angle_beta(cell.beta))
    c.add_data("cell", _cell_angle_gamma=CIF.cell_angle_gamma(cell.gamma))
    # atom block
    element_counter = {}
    carts = []
    for node, data in graph.nodes_iter(data=True):
        label = "%s%i"%(data['element'], node)
        c.add_data("atoms", _atom_site_label=
                                CIF.atom_site_label(label))
        c.add_data("atoms", _atom_site_type_symbol=
                                CIF.atom_site_type_symbol(data['element']))
        c.add_data("atoms", _atom_site_description=
                                CIF.atom_site_description(data['force_field_type']))
        coords = data['cartesian_coordinates']
        carts.append(coords)
        fc = np.dot(cell.inverse, coords) 
        c.add_data("atoms", _atom_site_fract_x=
                                CIF.atom_site_fract_x(fc[0]))
        c.add_data("atoms", _atom_site_fract_y=
                                CIF.atom_site_fract_y(fc[1]))
        c.add_data("atoms", _atom_site_fract_z=
                                CIF.atom_site_fract_z(fc[2]))
        c.add_data("atoms", _atom_type_partial_charge=
                                CIF.atom_type_partial_charge(data['charge']))
    # bond block
    # must re-sort them based on bond type (Mat Sudio)
    tosort = [(data['order'], (n1, n2, data)) for n1, n2, data in graph.edges_iter2(data=True)]
    for ord, (n1, n2, data) in sorted(tosort, key=lambda tup: tup[0]):
        type = CCDC_BOND_ORDERS[data['order']]
        dist = data['length'] 
        sym = data['symflag']


        label1 = "%s%i"%(graph.node[n1]['element'], n1)
        label2 = "%s%i"%(graph.node[n2]['element'], n2) 
        c.add_data("bonds", _geom_bond_atom_site_label_1=
                                    CIF.geom_bond_atom_site_label_1(label1))
        c.add_data("bonds", _geom_bond_atom_site_label_2=
                                    CIF.geom_bond_atom_site_label_2(label2))
        c.add_data("bonds", _geom_bond_distance=
                                    CIF.geom_bond_distance(dist))
        c.add_data("bonds", _geom_bond_site_symmetry_2=
                                    CIF.geom_bond_site_symmetry_2(sym))
        c.add_data("bonds", _ccdc_geom_bond_type=
                                    CIF.ccdc_geom_bond_type(type))
    
    print('Output cif file written to %s.cif'%c.name)
    file = open("%s.cif"%c.name, "w")
    file.writelines(str(c))
    file.close()

class Structure(object):

    def __init__(self, name):
        self.name = name
        self.cell = Cell()
        self.atoms = []
        self.bonds = []
        self.angles = []
        self.dihedrals = []
        self.impropers = []
        self.pairs = []
        self.charge = 0.0
        try:
            self.graph = nx.Graph()
        except NameError:
            self.graph = None

    

    def obtain_graph(self):
        """Attempt to assign bond and atom types based on graph analysis."""
        if self.graph is None:
            print("Warning atom and bond typing could not be completed due "+
                    "to lacking networkx module. All bonds will be of 'single' type" +
                    " which may result in a poor description of your system!")
            return

        for atom in self.atoms:
            self.graph.add_node(atom.ciflabel)
        for bond in self.bonds:
            at1, at2 = bond.atoms
            self.graph.add_edge(at1.ciflabel, at2.ciflabel)

    def compute_bonding(self, scale_factor=0.9):
        coords = np.array([a.coordinates for a in self.atoms])
        elems = [a.element for a in self.atoms]
        distmat = np.empty((coords.shape[0], coords.shape[0]))
        organics = set(["H", "C", "N", "O", "F", "Cl", "S", "B"])
        for (i,j) in zip(*np.triu_indices(coords.shape[0], k=1)):
            e1 = elems[i]
            e2 = elems[j]
            dist = self.min_img_distance(coords[i], coords[j])
            distmat[j,i] = dist
            covrad = COVALENT_RADII[e1] + COVALENT_RADII[e2]
            if(dist*scale_factor < covrad):
                # make sure hydrogens don't bond to metals (specific case..)
                if "H" in [e1, e2] and not set([e1, e2])<=organics:
                    pass
                else:
                    # figure out bond orders when typing.
                    bond = Bond(atm1=self.atoms[i], atm2=self.atoms[j], order=1)
                    bond.length = dist
                    self.bonds.append(bond)
                    self.atoms[i].neighbours.append(self.atoms[j].index)
                    self.atoms[j].neighbours.append(self.atoms[i].index)
        # make sure hydrogens don't bond to other hydrogens.. umm. except for H2
        delbonds = []
        for idx, bond in enumerate(self.bonds):
            a1, a2 = bond.atoms
            if a1.element == "H" and a2.element == "H":
                if len(a1.neighbours) > 1 or len(a2.neighbours) > 1:
                    delbonds.append(idx)
                    del(a1.neighbours[a1.neighbours.index(a2.index)])
                    del(a2.neighbours[a2.neighbours.index(a1.index)])
        for j in reversed(sorted(delbonds)):
            del(self.bonds[j])
        # re-index bonds after modification
        for idx, bond in enumerate(self.bonds):
            bond.index = idx
        self.compute_bond_image_flag()

    def get_atom_from_label(self, label):
        for atom in self.atoms:
            if atom.ciflabel == label:
                return atom

    def get_bond(self, atom1, atom2):
        for bond in self.bonds:
            if set((atom1, atom2)) ==  set(bond.atoms):
                return bond
        return None
    
    def get_angle(self, atom_a, atom_b, atom_c):
        for angle in self.angles:
            if (atom_a, atom_b, atom_c) ==  angle.atoms:
                return angle
        return None

    
    def compute_pair_terms(self):
        """Place holder for hydrogen bonding?"""
        for i in self.atoms:
            pair = PairTerm(i, i)
            self.pairs.append(pair)



class Bond(object):
    __ID = 0

    def __init__(self, atm1=None, atm2=None, order=1):
        self.index = self.__ID
        self.order = order
        self._atoms = (atm1, atm2)
        self.length = 0.
        self.symflag = 0
        self.ff_type_index = 0
        self.midpoint = np.array([0., 0., 0.])
        self.potential = None
        Bond.__ID += 1

    def compute_length(self, coord1, coord2):
        return np.linalg.norm(np.array(coord2) - np.array(coord1))

    def set_atoms(self, atm1, atm2):
        self._atoms = (atm1, atm2)

    def get_atoms(self):
        return self._atoms

    atoms = property(get_atoms, set_atoms)
    
    @property
    def indices(self):
        if not None in self.atoms:
            return (self.atoms[0].index, self.atoms[1].index)
        return (None, None)

    @property
    def elements(self):
        if not None in self.atoms:
            return (self.atoms[0].element, self.atoms[1].element)
        return (None, None)

class Angle(object):
    __ID = 0
    def __init__(self, abbond=None, bcbond=None):
        """Class to contain angles. Atoms are labelled according to the angle:
        a   c
         \ /
          b 
        """
        # atoms are obtained from the bonds.
        self._atoms = (None, None, None)
        if abbond is not None and bcbond is not None:
            self.bonds = (abbond, bcbond)
        else:
            self._bonds = (abbond, bcbond)
        self.ff_type_index = 0
        self.potential = None
        self._angle = 0.
        self.index = self.__ID
        Angle.__ID += 1

    def set_bonds(self, bonds):
        """order is assumed (ab_bond, bc_bond)"""
        self._bonds = bonds
        atm1, atm2 = bonds[0].atoms
        atm3, atm4 = bonds[1].atoms

        self._atoms = list(self._atoms)
        if atm1 in (atm3, atm4):
            self._atoms[0] = atm2
            self._atoms[1] = atm1
            if atm1 == atm3:
                self._atoms[2] = atm4
            else:
                self._atoms[2] = atm3

        elif atm2 in (atm3, atm4):
            self._atoms[0] = atm1
            self._atoms[1] = atm2
            if atm2 == atm3:
                self._atoms[2] = atm4
            else:
                self._atoms[2] = atm3
        self._atoms = tuple(self._atoms)

    def get_bonds(self):
        return self._bonds

    bonds = property(get_bonds, set_bonds)

    @property
    def ab_bond(self):
        return self._bonds[0]
   
    @property
    def bc_bond(self):
        return self._bonds[1]
   
    @property
    def atoms(self):
        return self._atoms

    @property
    def a_atom(self):
        return self._atoms[0]

    @property
    def b_atom(self):
        return self._atoms[1]

    @property
    def c_atom(self):
        return self._atoms[2]

class Dihedral(object):
    """Class to store dihedral angles
    a
     \ 
      b -- c
            \ 
             d

    """
    __ID = 0
    def __init__(self, angle1=None, angle2=None):
        self._atoms = (None, None, None, None)
        self._bonds = (None, None, None)
        # angles of the form: angle_abc, angle_bcd
        self._angles = (angle1, angle2)
        if not None in (angle1, angle2):
            self.angles = (angle1, angle2)
        self.ff_type_index = 0
        self.index = self.__ID
        self.potential = None
        Dihedral.__ID += 1

    def set_angles(self, angles):
        angle1, angle2 = angles
        bonds1 = angle1.bonds
        bonds2 = angle2.bonds

        if angle1.bc_bond != angle2.ab_bond:
            if angle1.bc_bond == angle2.bc_bond:
                angle2.bonds = tuple(reversed(bonds2))
            elif angle1.ab_bond == angle2.ab_bond:
                angle1.bonds = tuple(reversed(bonds1))
            elif angle1.ab_bond == angle2.bc_bond:
                angle1.bonds = tuple(reversed(bonds1))
                angle2.bonds = tuple(reversed(bonds2))
        self._angles = (angle1, angle2)

        assert angle1.bc_bond == angle2.ab_bond

        assert angle1.b_atom == angle2.a_atom

        assert angle1.c_atom == angle2.b_atom

        self._atoms = tuple([angle1.a_atom, angle1.b_atom,
                             angle2.b_atom, angle2.c_atom])
        self._bonds = tuple([angle1.ab_bond, angle1.bc_bond, angle2.bc_bond])

    def get_angles(self):
        return self._angles

    angles = property(get_angles, set_angles)

    @property
    def a_atom(self):
        return self._atoms[0]

    @property
    def b_atom(self):
        return self._atoms[1]

    @property
    def c_atom(self):
        return self._atoms[2]
    
    @property
    def d_atom(self):
        return self._atoms[3]
    
    @property
    def atoms(self):
        return self._atoms

    @property
    def ab_bond(self):
        return self._bonds[0]

    @property
    def bc_bond(self):
        return self._bonds[1]

    @property
    def cd_bond(self):
        return self._bonds[2]

    @property
    def bonds(self):
        return self._bonds

    @property
    def abc_angle(self):
        return self._angles[0]

    @property
    def bcd_angle(self):
        return self._angles[1]

class PairTerm(object):
    """Place holder for VDW and other
    non-bonded potentials.

    """
    __ID = 0

    def __init__(self, atm1=None, atm2=None):
        self.ff_type_index = 0
        self._atoms = (atm1, atm2)
        self.potential = None
        self.index = self.__ID
        PairTerm.__ID += 1
    
    def set_atoms(self, atm1, atm2):
        self._atoms = (atm1, atm2)

    def get_atoms(self):
        return self._atoms

    atoms = property(get_atoms, set_atoms)
    
    @property
    def indices(self):
        if not None in self.atoms:
            return (self.atoms[0].index, self.atoms[1].index)
        return (None, None)

    @property
    def elements(self):
        if not None in self.atoms:
            return (self.atoms[0].element, self.atoms[1].element)
        return (None, None)

class ImproperDihedral(object):
    """Class to store improper dihedral angles

    a
     \ 
      b -- c
      |
      d

    """
    __ID = 0
    def __init__(self, bond1=None, bond2=None, bond3=None):
        self._atoms = (None, None, None, None)
        self._bonds = (bond1, bond2, bond3)
        if not None in (bond1, bond2, bond3):
            self.bonds = (bond1, bond2, bond3)
        self.ff_type_index = 0
        self.potential = None
        self.index = self.__ID
        ImproperDihedral.__ID += 1
    
    def set_bonds(self, bonds):
        self._angles = bonds
        bond1, bond2, bond3 = bonds
        self._atoms = [None, None, None, None]
        for a1 in bond1.atoms:
            for a2 in bond2.atoms:
                for a3 in bond3.atoms:
                    if a1 == a2 == a3:
                        self._atoms[1] = a1

        ab1, ab2 = bond1.atoms
        ab3, ab4 = bond2.atoms
        ab5, ab6 = bond3.atoms

        if ab1 == self._atoms[1]:
            self._atoms[0] = ab2
        else:
            self._atoms[0] = ab1

        if ab3 == self._atoms[1]:
            self._atoms[2] = ab4
        else:
            self._atoms[2] = ab3

        if ab5 == self._atoms[1]:
            self._atoms[3] = ab6
        else:
            self._atoms[3] = ab5

    def get_bonds(self):
        return self._bonds

    bonds = property(get_bonds, set_bonds)

    @property
    def a_atom(self):
        return self._atoms[0]

    @property
    def b_atom(self):
        return self._atoms[1]

    @property
    def c_atom(self):
        return self._atoms[2]
    
    @property
    def d_atom(self):
        return self._atoms[3]
    
    @property
    def atoms(self):
        return self._atoms

    @property
    def ab_bond(self):
        return self._bonds[0]

    @property
    def bc_bond(self):
        return self._bonds[1]

    @property
    def bd_bond(self):
        return self._bonds[2]

class Atom(object):
    __ID = 0
    def __init__(self, element="X", coordinates=np.zeros(3)):
        self.element = element
        self.index = self.__ID
        self.neighbours = []
        self.ciflabel = None
        self.images = []
        self.rings = []
        self.molecule_id = (None, 0)
        self.is_cycle = False
        self.hybridization = ''
        self.force_field_type = None
        self.coordinates = coordinates
        self.charge = 0.
        self.ff_type_index = 0 # keeps track of the unique integer value assigned to the force field type
        Atom.__ID += 1
        self.image_index = -1 # If a copy, keeps the original index here.
        self.h_bond_donor = False # keep track of h-bonding atoms (for DREIDING)

    def scaled_pos(self, inv_cell):
        return np.dot(inv_cell, self.coordinates[:3])

    def in_cell_scaled(self, inv_cell):
        return np.array([i%1 for i in self.scaled_pos(inv_cell)])

    def in_cell(self, cell, inv_cell):
        return np.dot(self.in_cell_scaled(inv_cell), cell)

    @property
    def mass(self):
        return MASS[self.element]

    @property
    def atomic_number(self):
        return ATOMIC_NUMBER.index(self.element)

    def __copy__(self):
        a = Atom()
        a.element = self.element[:]
        # index determined automatically
        # neighbours re-calculated
        a.ciflabel = "%s%i"%(a.element, a.index)
        a.hybridization = self.hybridization[:]
        a.coordinates = self.coordinates.copy()
        a.charge = float(self.charge)
        a.ff_type_index = int(self.ff_type_index)
        a.force_field_type = self.force_field_type[:]
        a.image_index = self.index
        a.h_bond_donor = self.h_bond_donor
        
        return a

class Cell(object):
    def __init__(self):
        self._cell = np.identity(3, dtype=np.float64)
        # cell parameters (a, b, c, alpha, beta, gamma)
        self._params = (1., 1., 1., 90., 90., 90.)
        self._inverse = None

    @property
    def volume(self):
        """Calculate cell volume a.bxc."""
        b_cross_c = cross(self.cell[1], self.cell[2])
        return dot(self.cell[0], b_cross_c)

    def get_cell(self):
        """Get the 3x3 vector cell representation."""
        return self._cell

    def get_cell_inverse(self):
        """Get the 3x3 vector cell representation."""
        return self._inverse

    def set_cell(self, value):
        """Set cell and params from the cell representation."""
        # Class internally expects an array
        self._cell = np.array(value).reshape((3,3))
        self.__mkparam()
        self.__mklammps()
        self._inverse = np.linalg.inv(self.cell.T)

    # Property so that params are updated when cell is set
    cell = property(get_cell, set_cell)

    def get_params(self):
        """Get the six parameter cell representation as a tuple."""
        return tuple(self._params)

    def set_params(self, value):
        """Set cell and params from the cell parameters."""
        self._params = value
        self.__mkcell()
        self.__mklammps()
        self._inverse = np.linalg.inv(self.cell.T)

    params = property(get_params, set_params)

    def minimum_supercell(self, cutoff):
        """Calculate the smallest supercell with a half-cell width cutoff."""
        a_cross_b = np.cross(self.cell[0], self.cell[1])
        b_cross_c = np.cross(self.cell[1], self.cell[2])
        c_cross_a = np.cross(self.cell[2], self.cell[0])

        volume = np.dot(self.cell[0], b_cross_c)

        widths = [volume / np.linalg.norm(b_cross_c),
                  volume / np.linalg.norm(c_cross_a),
                  volume / np.linalg.norm(a_cross_b)]

        return tuple(int(math.ceil(2*cutoff/x)) for x in widths)

    def update_supercell(self, tuple):
        self._cell = np.multiply(self._cell.T, tuple).T
        self.__mkparam()
        self.__mklammps()
        self._inverse = np.linalg.inv(self._cell.T)

    @property
    def minimum_width(self):
        """The shortest perpendicular distance within the cell."""
        a_cross_b = cross(self.cell[0], self.cell[1])
        b_cross_c = cross(self.cell[1], self.cell[2])
        c_cross_a = cross(self.cell[2], self.cell[0])

        volume = dot(self.cell[0], b_cross_c)

        return volume / min(np.linalg.norm(b_cross_c), np.linalg.norm(c_cross_a), np.linalg.norm(a_cross_b))

    @property
    def inverse(self):
        """Inverted cell matrix for converting to fractional coordinates."""
        try:
            if self._inverse is None:
                self._inverse = np.linalg.inv(self.cell.T)
        except AttributeError:
            self._inverse = np.linalg.inv(self.cell.T)
        return self._inverse

    @property
    def crystal_system(self):
        """Return the IUCr designation for the crystal system."""
        #FIXME(tdaff): must be aligned with x to work
        if self.alpha == self.beta == self.gamma == 90:
            if self.a == self.b == self.c:
                return 'cubic'
            elif self.a == self.b or self.a == self.c or self.b == self.c:
                return 'tetragonal'
            else:
                return 'orthorhombic'
        elif self.alpha == self.beta == 90:
            if self.a == self.b and self.gamma == 120:
                return 'hexagonal'
            else:
                return 'monoclinic'
        elif self.alpha == self.gamma == 90:
            if self.a == self.c and self.beta == 120:
                return 'hexagonal'
            else:
                return 'monoclinic'
        elif self.beta == self.gamma == 90:
            if self.b == self.c and self.alpha == 120:
                return 'hexagonal'
            else:
                return 'monoclinic'
        elif self.a == self.b == self.c and self.alpha == self.beta == self.gamma:
            return 'trigonal'
        else:
            return 'triclinic'

    def __mkcell(self):
        """Update the cell representation to match the parameters."""
        a_mag, b_mag, c_mag = self.params[:3]
        alpha, beta, gamma = [x * DEG2RAD for x in self.params[3:]]
        a_vec = np.array([a_mag, 0.0, 0.0])
        b_vec = np.array([b_mag * np.cos(gamma), b_mag * np.sin(gamma), 0.0])
        c_x = c_mag * np.cos(beta)
        c_y = c_mag * (np.cos(alpha) - np.cos(gamma) * np.cos(beta)) / np.sin(gamma)
        c_vec = np.array([c_x, c_y, (c_mag**2 - c_x**2 - c_y**2)**0.5])
        self._cell = np.array([a_vec, b_vec, c_vec])

    def __mkparam(self):
        """Update the parameters to match the cell."""
        cell_a = np.sqrt(sum(x**2 for x in self.cell[0]))
        cell_b = np.sqrt(sum(x**2 for x in self.cell[1]))
        cell_c = np.sqrt(sum(x**2 for x in self.cell[2]))
        alpha = np.arccos(sum(self.cell[1, :] * self.cell[2, :]) /
                       (cell_b * cell_c)) * 180 / np.pi
        beta = np.arccos(sum(self.cell[0, :] * self.cell[2, :]) /
                      (cell_a * cell_c)) * 180 / np.pi
        gamma = np.arccos(sum(self.cell[0, :] * self.cell[1, :]) /
                       (cell_a * cell_b)) * 180 / np.pi
        self._params = (cell_a, cell_b, cell_c, alpha, beta, gamma)

    def __mklammps(self):
        a, b, c, alpha, beta, gamma = self._params
        lx = a
        xy = b*math.cos(gamma*DEG2RAD)
        xz = c*math.cos(beta*DEG2RAD)
        ly = math.sqrt(b**2 - xy**2)
        yz = (b*c*math.cos(alpha*DEG2RAD) - xy*xz)/ly
        lz = math.sqrt(c**2 - xz**2 - yz**2)
        self._lammps = (lx, ly, lz, xy, xz, yz)

    @property
    def lx(self):
        return self._lammps[0]
    @property
    def ly(self):
        return self._lammps[1]
    @property
    def lz(self):
        return self._lammps[2]
    @property
    def xy(self):
        return self._lammps[3]
    @property
    def xz(self):
        return self._lammps[4]
    @property
    def yz(self):
        return self._lammps[5]

    @property
    def a(self):
        """Magnitude of cell a vector."""
        return self.params[0]

    @property
    def b(self):
        """Magnitude of cell b vector."""
        return self.params[1]

    @property
    def c(self):
        """Magnitude of cell c vector."""
        return self.params[2]

    @property
    def alpha(self):
        """Cell angle alpha."""
        return self.params[3]

    @property
    def beta(self):
        """Cell angle beta."""
        return self.params[4]

    @property
    def gamma(self):
        """Cell angle gamma."""
        return self.params[5]

def clean(name):
    name = os.path.split(name)[-1]
    if name.endswith('.cif'):
        name = name[:-4]
    return name
