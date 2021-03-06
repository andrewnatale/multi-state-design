from model import Model
from SearchAlgorithm import SearchAlgorithm
from SimilarityMeasure import SimilarityMeasure
from io import *
from enumeration import enum
from copy import *
import numpy
import ast
import datetime
import warnings

RESIDUES = enum('A', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'V', 'W', 'Y');

# NOTE: Read in target frequencies first before reading data to figure out the number of positions to be examined

class Optimizer(object):
    """
    Optimizes the hyperparameters of a model
    """

    # TODO: make all parameters generic

    models = {}                                   # Map<hyperparams, Model> of the input data, since values are precalculated
    optimizationAlgorithm = SearchAlgorithm()     # the algorithm to be used
    #similarityMeasure = SimilarityMeasure();     # the similarlity measure to be used
    nPositions = 0                                # number of positions examined
    contiguousPositions = True                    # are the set of positions contiguous
    positionMap = None                            # used to map from non-contiguous that start on 0 positions to [0, nPositions]
    minPosition = 0                               # position offset for indexing
    targetFrequencies = numpy.array(0)            # float[position][residue] internal representation of the target frequencies
    MACROSTATES = enum()                          # enum of the macrostates
    nMacrostates = 0                              # number of macrostates
    continuousBoltzmann = False                   # are we using a continuous set of boltzmann temps
    targetFreqsRead = False

    def __init__(self, macrostates=None, continuousBoltzmann=False, contiguousPositions=True):
        """
        Default constructor.

        @param macrostates            enum of the macrostates to be considered
        @param continuousBoltzmann    bool, are microstate data provided
        @param contiguousPositions    bool, are the positions aligned to a contiguous set of positions in the target?
        """

        self.MACROSTATES = macrostates
        # turn this enum into what we really need for indexing - a dictionary
        # this is a kludgy solution, but it would take a while to dig all the enum stuff out of this code
        self.macStateToIndex = {}
        for elem in self.MACROSTATES.__dict__:
            if elem != 'size':
                if type(self.MACROSTATES.__dict__[elem]) is int:
                    self.macStateToIndex[elem] = self.MACROSTATES.__dict__[elem]
        self.nMacrostates = self.MACROSTATES.size
        self.continuousBoltzmann = continuousBoltzmann
        self.models = {}
        self.nPositions = 0
        self.minPosition = 0
        self.targetFrequencies = numpy.array(0)
        self.contiguousPositions = contiguousPositions
        self.targetFreqsRead = False
        if not contiguousPositions:
            self.positionMap = {}
        else:
            self.positionMap = None

    # STATIC
    def copyFromExisting(existing):
        """
        Deep copies an existing Optimizer
        @param existing        Optimizer to be copied
        @return Optimizer
        """

        newOptimizer = Optimizer(existing.MACROSTATES)
        newOptimizer.minPosition = existing.minPosition
        newOptimizer.nPositions = existing.nPositions
        newOptimizer.targetFrequencies = numpy.array(existing.targetFrequencies)
        newOptimizer.models = dict(existing.models)
        #newOptimizer.similarityMeasure = existing.similarityMeasure;
        newOptimizer.optimizationAlgorithm = existing.optimizationAlgorithm
        newOptimizer.contiguousPositions = existing.contiguousPositions
        newOptimizer.targetFreqsRead = existing.targetFreqsRead
        if not existing.contiguousPositions:
            newOptimizer.positionMap = deepcopy(existing.positionMap)

        return newOptimizer

    # TODO: change the file return type to file read return
    def readTargetFrequencies(self, source, posPicker=None):
        """
        Reads the target frequencies from a FASTA file. Call this before reading data
        Note: when optimizing against a set of positions that are not contiguous, this function
        *MUST* be called before calling a read*Data function. Doing otherwise will void all warranties
        and promises that calculations will be correct.

        @param source            string pointing to the location of the input FASTAs
        @return array of the target frequencies
        """
        # resToIndex is used to convert a one-letter AA code to an index, which is in alphabetical order
        resToIndex = {'A':0, 'C':1, 'D':2, 'E':3, 'F':4, 'G':5, 'H':6, 'I':7, 'K':8, 'L':9, 'M':10, 'N':11, 'P':12, 'Q':13, 'R':14, 'S':15, 'T':16, 'V':17, 'W':18, 'Y':19}
        infile = open(source, 'r', encoding='utf-8')

        # figure out the number of positions
        infile.readline() # skip the first line (>NULL)
        entry = ""
        thisLine = infile.readline()
        while thisLine[0] != '>':
            entry += thisLine
            thisLine = infile.readline()
        self.nPositions = len(entry) - 1
        # case where the entries end with a dash
        if entry[-2] == 0:
            nPositions -= 1
        # allocate space for a double[][]
        self.targetFrequencies = numpy.zeros([self.nPositions, 20], dtype = float)

        # read entries
        # 2/17 note: this has been modified to be ok with files that have unaligned positions, i.e. '-' in sequence
        infile.seek(0)    # go back to the start
        nEntries = numpy.zeros([self.nPositions], dtype = int)
        thisEntry = ""
        for line in infile:
            if line[0] == '>':        # line starts w/ '>', indicating start of a new entry
                if thisEntry == "":    # no entry to process
                    pass
                else:                # add the residues in this entry to the counts
                    for i in range(self.nPositions):
                        #print(thisEntry[i], end='');
                        if thisEntry[i] != '-':    # only when there is a residue aligned here
                            try:
                                self.targetFrequencies[i][resToIndex[thisEntry[i]]] += 1
                                nEntries[i] += 1
                            except KeyError:    # non-single residue code. skip
                                continue
                    thisEntry = ""    # then clear it to read the next entry
                    #print();
            else:                    # middle of an entry, append this line
                thisEntry += line
        # counts to frequencies
        for i in range(self.nPositions):
            for j in range(20):
                self.targetFrequencies[i][j] /= nEntries[i]

        infile.close()

        # 2/17 added parts to allow for removal of superfluous positions
        if posPicker != None:
            self.contiguousPositions = False
            indices = self.positionReindexerFASTA(posPicker)
            self.nPositions = len(indices)
            freqs = numpy.zeros([self.nPositions, 20])
            for i in range(len(indices)):
                freqs[i] = self.targetFrequencies[indices[i]]
            self.targetFrequencies = freqs
            ## make the re-mapping indexer
            #for i in range(self.nPositions):
            #    self.positionMap[indices[i]] = i;

        self.targetFreqsRead = True
        return numpy.array(self.targetFrequencies)

    # read raw macrostate data
    # TODO: change the file return type to file read return
    def readData(self, source):
        """
        Reads in a tab-delimited file of ensembles encoding macrostate data

        @param source    a string pointing to the location of the tab-delimited file
        @return void
        """
        if not self.targetFreqsRead:
            warnings.warn("Hey, call the read target freqs functions first!", UserWarning)

        # used to convert the input dict to an array
        indexToRes = {0:'A', 1:'C', 2:'D', 3:'E', 4:'F', 5:'G', 6:'H', 7:'I', 8:'K', 9:'L', 10:'M', 11:'N', 12:'P', 13:'Q', 14:'R', 15:'S', 16:'T', 17:'V', 18:'W', 19:'Y'}

        # convert strings to manipulate-able values
        self.models.clear()

        infile = open(source, 'r')
        isFirstLine = True
        isFirstEntry = True
        self.minPosition = 65535        # used for offsetting indices in Macrostate

        placeHolderWeights = numpy.array([0, 0, 0, 0])
        placeHolderSteep = 1
        for line in infile:
            # ignore first line since they're just column headers
            if isFirstLine:
                isFirstLine = False
            else:
                entries = line.split('\t')        # entries: a list of strings
                macrostate = entries[0]        # string
                backrubT = entries[1]            # string
                ensembleS = entries[2]            # string
                boltzmanT = entries[3]            # string
                position = entries[4]            # string
                energies = ast.literal_eval(entries[5])        # ast.literal_eval converts a string to a dictionary

                # now ints
                macrostate = self.macStateToIndex[macrostate]
                position = int(position)
                ensembleS = int(ensembleS)

                # record minposition - assumes that the first entry is at first position
                # TODO: fix this to actually find minimum position
                if isFirstEntry:
                    self.minPosition = position
                    isFirstEntry = False

                # skip superfluous positions
                if position < self.minPosition or position >= self.minPosition + self.nPositions:
                    continue

                # now doubles
                backrubT = float(backrubT)
                if boltzmanT == "min":    # account for the possible text values
                    boltzmanT = 0.0
                elif boltzmanT == "mean":
                    boltzmanT = -1.0    # use -1 to represent inf - you can't really do math with numpy.inf
                else:
                    boltzmanT = float(boltzmanT)

                # calc model ID from the strings because that's always unique
                ID = Optimizer.calcParamsID(backrubT, ensembleS, boltzmanT)

                # now an array
                temp = numpy.zeros([20])
                for i in range(20):
                    temp[i] = energies[indexToRes[i]]
                energies = temp

                # put this read into the internal small, colorful shells structure
                if ID in self.models:
                    self.models[ID].addMacrostateData(macrostate, position, energies)
                else:
                    model = Model(self.MACROSTATES, ensembleS, backrubT, boltzmanT, placeHolderWeights, placeHolderSteep, self.nPositions, self.minPosition)
                    model.addMacrostateData(macrostate, position, energies)
                    self.models[ID] = model

        infile.close()
        return None

    # read raw microstate data
    def readMicrostateData(self, source:str, minPosition:int):
        """
        Reads in raw microstate data. Unlike readData(), this function does not assume anything
        about the min position and it must be supplied manually

        @param source        string of the input file
        @param minPosition    int of the lowest position number
        @return void
        """

        if not self.targetFreqsRead:
            warnings.warn("Hey, call the read target freqs functions first!", UserWarning)

        self.models.clear()
        self.minPosition = minPosition
        maxPos = 0

        indexToRes = {0:'A', 1:'C', 2:'D', 3:'E', 4:'F', 5:'G', 6:'H', 7:'I', 8:'K', 9:'L', 10:'M', 11:'N', 12:'P', 13:'Q', 14:'R', 15:'S', 16:'T', 17:'V', 18:'W', 19:'Y'}

        infile = open(source, 'r')

        placeHolderWeights = None
        placeHolderSteep = 0
        placeHolderBoltzmannT = 0
        placeHolderEnsemble = 0

        n = 0
        isFirstLine = True
        #line = infile.readline()
        #while true:
        for line in infile:
            # ignore first line since they're just column headers
            if isFirstLine:
                isFirstLine = False
            else:
                n += 1
                entries = line.split('\t')
                # print(entries)
                macrostate = entries[0]
                backrubT = entries[1]
                position = int(entries[2])
                #backbone = entries[3]
                energies = ast.literal_eval(entries[4])

                # skip superfluous positions
                if position < self.minPosition or position >= self.minPosition + self.nPositions:
                    print('skipping %d' % position)
                    continue

                # convert from string to useful data types
                backrubT = float(backrubT)
                macrostate = self.macStateToIndex[macrostate]
                position = int(position)
                temp = numpy.zeros([20])
                for i in range(20):
                    temp[i] = energies[indexToRes[i]]
                energies = temp

                if position > maxPos:
                    maxPos = position
                    print(maxPos)

                ID = Optimizer.calcParamsID(backrubT, None, None)
                if ID in self.models:
                    self.models[ID].addMicrostateData(macrostate, position, energies)
                else:
                    model = Model(self.MACROSTATES, placeHolderEnsemble, backrubT, placeHolderBoltzmannT, placeHolderWeights, placeHolderSteep, self.nPositions, self.minPosition, True, self.positionMap)
                    model.addMicrostateData(macrostate, position, energies)
                    self.models[ID] = model

            #line = infile.readline()
            #if not line: # EOF
            #    break

        if self.contiguousPositions:
            self.nPositions = maxPos - minPosition + 1
        infile.close()
        return None

    def positionReindexer(data:str):
        """
        Used to offset arbitrary positions to start with 0. Used when converting files.
        The file should have three columns. The first is the index in the alignment, the second I have no idea,
        the third is the index in the residue sequence.

        @param data        string pointing to the indices file
        @return int[] where each entry holds the unaligned position that is mapped to the index
        """
        infile = open(data, 'r');
        indices = [];
        n = 0;
        for line in infile:
            entries = line.split(' ');
            i = entries[2].strip('\n');
            indices[i] = n;
            n += 1;
        indices['nPos'] = n;
        infile.close();
        return indices;

    def positionReindexerFASTA(self, data:str):
        """
        Since we may be aligning to a FASTA sequence with more positions,
        we strip the superfluous positions from the read in FASTA. Used when reading files.
        The file should have three columns. The first is the index in the alignment, the second I have no idea,
        the third is the index in the residue sequence.

        @param data        string pointing to the file
        @return    int[] where the index is the corrected/reindexed position, and the value is the original index
        """

        infile = open(data, 'r');
        index = [];
        i = 0;
        for line in infile:
            entries = line.split(' ');
            index.append(int(entries[0]));
            self.positionMap[int(entries[2].strip('\n'))] = i;
            i += 1;
        indices = numpy.array(index);
        return indices;

    # TODO: change the return type to file write return val
    def writeFrequenciesToFASTA(self, frequencies:numpy.array, outFileName:str, precision:int=3):
        """
        Writes the 2D residue frequencies to a FASTA file

        @param frequencies        double[positio][residue] of relative frequencies
        @param outfile            string of output filename
        @param precision        int, optional, number of places behind the decimal point, default is 3
        @return int                1 if failure, 0 if succeeds
        """
        if outFileName.split('.')[-1] != 'fasta':
            outFileName += ".fasta";

        try:
            outfile = open(outFileName, 'w');
        except FileExistsError:
            print("Output file already exists\n");
            return 1
        nEntries = numpy.power(10, precision);
        numbers = numpy.round(frequencies * nEntries);
        residueToWrite = numpy.zeros([self.nPositions], dtype = int);
        #print(numbers);
        residues = "ACDEFGHIKLMNPQRSTVWY";
        for i in range(nEntries):
            outfile.write("> Null\n");
            for j in range(self.nPositions):
                while numbers[j][residueToWrite[j]] == 0 and residueToWrite[j] < 19:
                    residueToWrite[j] += 1;
                numbers[j][residueToWrite[j]] -= 1;
                outfile.write(residues[residueToWrite[j]]);
            outfile.writelines("\n");
        outfile.close();
        return 0;

    def writeBestParamsToText(self, out:str):
        """
        Writes the best parameters found to a human-readable text file.
        Overwrites without warning.

        @param out        string of name of output file
        @return void
        """
        if out.split('.')[-1] != 'txt':
            out += ".txt";
        outfile = open(out, 'w');
        bestVals = self.getBestParameters();
        outfile.write("Ensemble Size: {:d}\n".format(bestVals['ensembleSize']));
        outfile.write("Backrub temperature: {:.1f}\n".format(bestVals['backrubTemp']));
        bt = bestVals['boltzmannTemp'];
        if bt > 0:
            outfile.write("Boltzmann averaging temperature: {:.9f}\n".format(bestVals['boltzmannTemp']));
        elif bt == 0:
            outfile.write("Boltzmann averaging temperature: mean\n");
        else:
            outfile.write("Boltzmann averaging temperature: inf\n");
        outfile.write("Steepness: {:.9f}\n".format(bestVals['steepness']));
        outfile.write("Weights: ");
        for i in range(self.MACROSTATES.size):
            outfile.write("{:.4f} ".format(bestVals['weights'][i]));
        outfile.write("\nMatch: {:.4f}\n".format(bestVals['match']));
        outfile.write("Algorithm: {:s}\n".format(self.optimizationAlgorithm.__str__()));
        outfile.write("Similarity measure: {:s}\n".format(self.optimizationAlgorithm.similarityMeasure.__str__()));
        outfile.write("Elapsed time: {:s}\n".format(str(self.optimizationAlgorithm.elapsedTime)));
        outfile.close();

    # generate a unique reproducible key for a combination of hyperparameters
    # hash or plaintext string?
    # STATIC
    def calcParamsID(param1, param2, param3):
        """
        Generates a unique and reproducable ID string for each combination of parameters, either
        by concactenating the toString representations or hashing it all
        Is a static method.

        @param param1            backrub temperature
        @param param2            ensemble size
        @param param3            Boltzmann averaging temperature
        @return                    a unique string
        """
        #longString = hashlib.sha1(macrostate).hexdigest() + hashlib.sha1(backrubT).hexdigest() + hashlib.sha1(ensembleS).hexdigest();
        #longString += hashlib.sha1(boltzmanT).hexdigest() + hashlib.sha1(weights).hexdigest() + hashlib.sha1(steep);
        #return hashlib.sha1(longString).hexdigest();
        return str(param1) + " " + str(param2) + " " + str(param3);

    def getModelByParams(self, param1, param2, param3):
        """
        Gets a model by the specified pre-determined parameters.
        Return is a reference and the return object should not be
        directly modified. use the Model.createFromExisting() function on it
        to generate a copy.

        @param param1            backrub temperature
        @param param2            ensemble size
        @param param3            Boltzmann averaging temperature
        @return Model with specified params
        """
        return self.models[Optimizer.calcParamsID(param1, param2, param3)];

    def useAlgorithm(self, algorithm:SearchAlgorithm):
        """
        Changes the search algorithm used by the optimizer

        @param algorithm        new SearchAlgorithm
        @return void
        """
        self.optimizationAlgorithm = algorithm;

    def optimize(self):
        """
        Starts the optimization process

        @param void
        @return void
        """
        self.optimizationAlgorithm.iterate();

    def verifyFoundParams(self, ensembleSize, backrubT, boltzmannT, steepness, weights):
        """
        Run some found parameters against this model to see the match

        @param ensembleSize            int of found size
        @param backrubT                float of found backrub temperature
        @param boltzmannT            float of found boltzmann averaging temperature
        @param steepness            float of found steepness
        @param weights                float[] of found weights
        @return    float on [0, 1] of match to target
        """
        model = Model.constructFromExisting(self.getModelByParams(backrubT, ensembleSize, boltzmannT), ensembleSize, backrubT, boltzmannT, weights, steepness);
        return self.optimizationAlgorithm.similarityMeasure.getSimilarityMeasure(model.getFrequencies());

    def getFrequenciesByParams(self, ensembleSize, backrubT, boltzmannT, steepness, weights):
        """
        Gets the frequencies corresponding to a particular set of hyperparams

        @param ensembleSize            int of found size
        @param backrubT                float of found backrub temperature
        @param boltzmannT            float of found boltzmann averaging temperature
        @param steepness            float of found steepness
        @param weights                float[] of found weights
        @return    float[][] of the relative frequencies
        """
        model = Model.constructFromExisting(self.getModelByParams(backrubT, ensembleSize, boltzmannT), ensembleSize, backrubT, boltzmannT, weights, steepness);
        return model.getFrequencies();

    def getBestParameters(self):
        """
        Returns a dictionary of the best parameters found.
        Keys:
            'ensembleSize'
            'backrubTemp'
            'boltzmannTemp'
            'steepness'
            'weights'
            'match'

        @param void
        @return Map<string, float>
        """
        return self.optimizationAlgorithm.getBestParameters();

    def getBestFrequencies(self):
        """
        Returns the best frequencies found

        @param void
        @return float[][] of frequencies
        """
        return self.optimizationAlgorithm.getBestFrequencies();
