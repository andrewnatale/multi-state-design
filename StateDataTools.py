import numpy as np
from Bio import SeqIO
import datetime
import pickle as pkl

class StateProcessor(object):
    """Class to load, process, and write out Rosetta fixbb data."""

    # standard aa to # map
    aminotonumber = {'*': 0, 'W': 1,
                     'F': 2, 'Y': 3,
                     'L': 4, 'I': 5,
                     'M': 6, 'V': 7,
                     'C': 8, 'A': 9,
                     'G': 10, 'P': 11,
                     'S': 12, 'T': 13,
                     'N': 14, 'Q': 15,
                     'H': 16, 'R': 17,
                     'K': 18, 'D': 19,
                     'E': 20}

    def __init__(self, position_ids):
        """Set some gatekeeping variables to make sure things are done in
        the right order."""

        self.seq_loaded = False
        self.labeled = False
        self.default_name = 1
        self.state_count = 0
        self.position_ids = position_ids
        self.state_list = []
        # don't need stop codons here
        if '*' in self.aminotonumber:
            del self.aminotonumber['*']
        # generate a dictionary for reverse number to amino acid lookups
        self.numbertoamino = {}
        for key in self.aminotonumber:
            self.numbertoamino[self.aminotonumber[key]] = key

    def seq_from_fasta(self, native_seq_fasta):
        """Load a reference sequence from a fasta file using Biopython.
        Only uses the first entry in the fasta file if multiple are present."""

        if self.seq_loaded:
            print('Already loaded a reference sequence, cannot load another!')
            exit(0)
        # use BioPython's SeqIO to load a fasta
        reference = list(SeqIO.parse(native_seq_fasta, 'fasta'))
        # get info from the first fasta entry
        self.native_seq = str(reference[0].seq)
        self.header = str(reference[0].id)
        self.seq_loaded = True

    def seq_from_string(self, native_seq_string, identifier=None):
        """Load a reference sequence from an input string."""

        if self.seq_loaded:
            print('Already loaded a reference sequence, cannot load another!')
            exit(0)
        self.native_seq = native_seq_string
        if identifier:
            self.header = identifier
        else:
            self.header = 'null'
        self.seq_loaded = True

    def generate_labels(self):
        """Compose data labels from available information."""

        if not self.seq_loaded:
            print('Must load sequence before generating labels!')
            exit(0)
        # generate letter/number sequence labels for heatmaps
        # wt_indicators is a list of indices for normalizing arrays
        self.sequence_labels = []
        self.wt_indicators = []
        for position in self.position_ids:
            self.sequence_labels.append('%s%d' % (self.native_seq[position-1], position))
            self.wt_indicators.append(self.aminotonumber[self.native_seq[position-1]] - 1)
        # order amino acid labels in the same way they will be in the arrays
        self.mutation_labels = []
        for key in sorted(self.numbertoamino):
            self.mutation_labels.append(self.numbertoamino[key])
        self.labeled = True

    def load_state_pickle(self, data_file, state_name=None):
        """Loads a pickle file into a Macrostate object. The main part of
        a macrostate is a 4D array containing rosetta scores. It also contains
        a dictionary of labels to identify the indices."""

        # it is necessary to call the 'generate_labels' method before loading
        # data, because we need the 'wt_indicators' list in order to init
        # macrostate objects
        if not self.labeled:
            print('Must generate labels before loading state data!')
            exit(0)
        if not state_name:
            state_name = 'state_%d' % self.default_name
            self.default_name += 1
        # the pickle file needs to consist of a tuple with the first item being
        # a 3D array of rosetta energy scores, and the second item being a
        # dictionary mapping the names of microstates to indices in the array
        with open(data_file, 'rb') as data:
            state_array, state_labels = pkl.load(data)
        self.state_list.append(Macrostate(state_array, state_labels, state_name, self.wt_indicators))
        self.state_count += 1

    def write_microstate_seqs(self, position_range='all', label_string=None):
        """Find and write lowest energy microstate sequences in fasta format."""

        # try to handle several ways of supplying target positions - the can be
        # a list or a range iterator
        if position_range == 'all':
            position_range = self.position_ids
        else:
            # convert iterator to list
            position_range = [i for i in position_range]
        # convert position numbers into indices
        selected_indices = [elem[0] for elem in enumerate(self.position_ids) if elem[1] in position_range]
        if not label_string:
            label_string = datetime.datetime.today()
        # generate one fasta file for every loaded macrostate
        for state in self.state_list:
            with open('%s_%s.fasta' % (state.state_name, label_string), 'w') as fasta_out:
                # generate one fasta entry for each microstate
                for microstate in state.microstate_list:
                    # compose an identifier for each fasta entry
                    id_string = '>%s %s %s positions: %s' % (state.state_name,
                                                             microstate.substate_label,
                                                             microstate.us_name,
                                                             str(position_range).strip('[]'))
                    # ask the microstate what its lowest energy sequence is
                    best_seq = ''
                    # only pick out specified positions
                    for idx,code in enumerate(microstate.find_best_seq()):
                        if idx in selected_indices:
                            best_seq += self.numbertoamino[code]
                    # write the fasta entry
                    fasta_out.write('%s\n' % id_string)
                    fasta_out.write('%s\n' % best_seq)

    def write_macrostate_energy_tsv(self, outname='default', position_range='all'):
        """Write out averaged macrostate data in a format that Zhang's
        multistate design optimizer can read."""

        # try to handle several ways of supplying target positions - the can be
        # a list or a range iterator
        if position_range == 'all':
            position_range = self.position_ids
        else:
            # convert iterator to list
            position_range = [i for i in position_range]
        # convert position numbers into indices
        selected_indices = [elem[0] for elem in enumerate(self.position_ids) if elem[1] in position_range]
        # give the output file a unique default name
        if outname == 'default':
            outname = 'avg_macrostates_%s.tsv' % datetime.datetime.today()
        # write a tsv file in the required format
        with open(outname, 'w') as tsvfile:
            tsvfile.write('average macrostate energies for positions: %s\n' % str(position_range).strip('[]'))
            for state in self.state_list:
                for pos_idx in selected_indices:
                    # write data identifiers in the first 5 fields
                    tsvfile.write('%s\t%s\t%s\t%s\t%s\t' % (state.state_name, # macrostate name
                                                            '0.9', # backrub temp
                                                            str(state.microstate_count), # how many microstates?
                                                            'mean', # how were microstates averaged?
                                                            #str(self.position_ids[pos_idx]), # position in sequence
                                                            str(pos_idx+1) # remap positions to avoid confusing the optimizer
                                                            )
                                  )
                    # here's the fun part - in the 6th field write the data in
                    # the form of a python dictionary, because that's what the
                    # optimizer wants to read
                    tsvfile.write('{')
                    for mut_idx, energy in np.ndenumerate(state.avg_state_array[:,pos_idx]):
                        tsvfile.write("'%s':%f, " % (self.numbertoamino[mut_idx[0]+1], energy))
                    tsvfile.write('}\n')

    def write_microstate_energy_tsv(self, outname='default', position_range='all'):
        """Write out all microstate data in a format that Zhang's
        mutistate design optimizer can read."""

        # try to handle several ways of supplying target positions - the can be
        # a list or a range iterator
        if position_range == 'all':
            position_range = self.position_ids
        else:
            # convert iterator to list
            position_range = [i for i in position_range]
        # convert position numbers into indices
        selected_indices = [elem[0] for elem in enumerate(self.position_ids) if elem[1] in position_range]
        # give the output file a unique default name
        if outname == 'default':
            outname = 'microstates_%s.tsv' % datetime.datetime.today()
        # write a tsv file in the required format
        with open(outname, 'w') as tsvfile:
            tsvfile.write('microstate energies for positions: %s\n' % str(position_range).strip('[]'))
            for state in self.state_list:
                for microstate in state.microstate_list:
                    for pos_idx in selected_indices:
                        # write data identifiers in the first 4 fields
                        tsvfile.write('%s\t%s\t%s\t%s\t' % (state.state_name, # macrostate name
                                                            '0.9', # backrub temp
                                                            #str(self.position_ids[pos_idx]), # position
                                                            str(pos_idx+1), # remap positions to avoid confusing the optimizer
                                                            '%s_%s' % (microstate.substate_label, microstate.us_name) # microstate identifier
                                                            )
                                      )
                        # here's the fun part - in the 5th field write the data in
                        # the form of a python dictionary, because that's what the
                        # optimizer wants to read
                        tsvfile.write('{')
                        for mut_idx, energy in np.ndenumerate(microstate.microstate_array[:,pos_idx]):
                            tsvfile.write("'%s':%f, " % (self.numbertoamino[mut_idx[0]+1], energy))
                        tsvfile.write('}\n')

class Macrostate(object):
    """Class to hold and organize data for one macrostate composed of many
    microstates."""

    def __init__(self, state_array, state_labels, state_name, wt_indicators, exp_scale_factor=3.0):
        """Load a macrostate, adjust all energies to make WT = 0, and
        store each microstate as an object."""

        self.state_name = state_name
        self.state_array = state_array
        self.state_labels = state_labels
        self.microstate_list = []
        self.microstate_count = 0
        # iterate over the label dictionary to access each microstate
        for label in state_labels:
            us_idx = state_labels[label]
            # adjust each position column in each microstate to be relative to WT
            for pos_idx, wt_idx in enumerate(wt_indicators):
                self.state_array[us_idx,:,pos_idx] \
                  -= self.state_array[us_idx,wt_idx,pos_idx]
            # store each microstate in a list
            self.microstate_list.append(Microstate(self.state_array[us_idx,:,:], label, us_idx))
            self.microstate_count += 1
        # build averaged and exponential arrays
        self.avg_state_array = np.mean(self.state_array, 0)
        self.exp_state_array = np.exp((-1.0 * self.avg_state_array) / exp_scale_factor)

    def list_microstates(self):
        # print some info for troubleshooting
        print('%d microstates loaded' % self.microstate_count)
        for microstate in self.microstate_list:
            print(microstate.substate_label, microstate.us_name, microstate.sub_idx, microstate.us_idx)
            print(microstate.microstate_array)


class Microstate(object):
    """Class to hold data for one microstate."""

    def __init__(self, state_array, state_labels, us_idx):
        """Store data and labels for an individual microstate."""

        self.microstate_array = state_array
        self.substate_label, self.us_name = state_labels
        self.us_idx = us_idx

    def find_best_seq(self):
        """Determine the lowest energy amino acid at each position and return
        a list of the amino acid numeric ids."""

        # for each position, find the index of the lowest energy score (add 1 to
        # make it simple to lookup in the mapping dictionary) and save to a list
        self.lowest_scores = []
        for n in range(self.microstate_array.shape[1]):
            self.lowest_scores.append(self.microstate_array[:,n].argmin() + 1)
        return self.lowest_scores
