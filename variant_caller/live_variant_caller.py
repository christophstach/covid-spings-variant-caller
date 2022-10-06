
import functools
import operator
import pickle
import math

import pysam
import numpy as np

from tqdm import tqdm
from pysam import AlignedSegment
from time import strftime, localtime

from .structs import Site
from .utils import genotype_likelihood, genotype_likelihood, from_phred_scale, to_phred_scale

class LiveVariantCaller:
    def __init__(self, referenceFasta: str, minBaseQuality: int, minMappingQuality: int, minTotalDepth: int, minEvidenceDepth: int, minEvidenceRatio: float, maxVariants: int):
        self.minBaseQuality = minBaseQuality
        self.minMappingQuality = minMappingQuality
        self.minTotalDepth = minTotalDepth
        self.minEvidenceDepth = minEvidenceDepth
        self.minEvidenceRatio = minEvidenceRatio
        self.maxVariants = maxVariants
        
        self.fastaFile = pysam.FastaFile(referenceFasta)

        self.reset_memory()

    def __del__(self):
        self.fastaFile.close()

    def reset_memory(self):
        self.memory: dict[int, Site] = {}

    def create_checkpoint(self, filename):
        timestamp = strftime('[%Y-%m-%d %H:%M:%S]', localtime())
        print(f'{timestamp} Creating checkpoint {filename}')

        file = open(filename, 'wb')
        pickle.dump(self.memory, file)
        file.close()

    def load_checkpoint(self, filename):
        timestamp = strftime('[%Y-%m-%d %H:%M:%S]', localtime())
        print(f'{timestamp} Loading checkpoint {filename}')

        file = open(filename, 'rb')
        self.memory,  = pickle.load(file)
        file.close()

    def process_bam(self, inputBam: str, referenceIndex=0):
        bamFile = pysam.AlignmentFile(inputBam, 'rb')
        
        pileupColumns = bamFile.pileup(
            min_mapping_quality=self.minMappingQuality,
            min_base_quality=self.minBaseQuality,
            reference=self.fastaFile.references[referenceIndex]
        )

        timestamp = strftime('[%Y-%m-%d %H:%M:%S]', localtime())
        progressBar = tqdm(
            pileupColumns, 
            desc=f'{timestamp} Processing {inputBam}',
            total=bamFile.get_reference_length(self.fastaFile.references[referenceIndex])
        )

        for pileupColumn in progressBar:
            self.process_pileup_column(pileupColumn)


        bamFile.close()

    def process_pileup_column(self, pileupColumn: AlignedSegment):
        totalDepth = len(pileupColumn.pileups)

        if pileupColumn.reference_pos not in self.memory:
            reference = self.fastaFile.fetch(reference=pileupColumn.reference_name)

            self.memory[pileupColumn.reference_pos] = {
                'reference': reference[pileupColumn.reference_pos],
                'totalDepth': totalDepth,
                'baseQualities': {}
            }
        else:
            self.memory[pileupColumn.reference_pos]['totalDepth'] += totalDepth

        for pileup in pileupColumn.pileups:
            self.process_pileup_at_position(pileupColumn.reference_pos, pileup)

    def process_pileup_at_position(self, position: int, pileup):
        if not pileup.is_del and not pileup.is_refskip:
            base = pileup.alignment.query_sequence[pileup.query_position]

            if base not in self.memory[position]['baseQualities'].keys():
                # We could store more information here in the memory. But as the Base Qualty is the the only information that matters for further calculation we 
                # save memory and only store them

                self.memory[position]['baseQualities'][base] = []
            else:
                self.memory[position]['baseQualities'][base].append(pileup.alignment.query_qualities[pileup.query_position])

    def write_vcf(self, outputVfc: str):
        timestamp = strftime('[%Y-%m-%d %H:%M:%S]', localtime())
        progressBar = tqdm(
            self.memory, 
            desc=f'{timestamp} Writing VCF to {outputVfc}',
            total=len(self.memory.keys())
        )

        vcfHeader = pysam.VariantHeader()

        vcfHeader.add_meta('INFO', items=[
            ('ID', 'TD'),
            ('Number', 1),
            ('Type', 'Integer'),
            ('Description', 'Total Depth')
        ])

        vcfHeader.add_meta('INFO', items=[
            ('ID', 'ED'),
            ('Number', 1),
            ('Type', 'Integer'),
            ('Description', 'Evidence Depth')
        ])

        vcfHeader.add_meta('INFO', items=[
            ('ID', 'GL'),
            ('Number', 1),
            ('Type', 'Float'),
            ('Description', 'Genotype likelihoods comprised of comma separated floating point log10-scaled likelihoods for all possible genotypes given the set of alleles defined in the REF and ALT fields')
        ])

        vcfHeader.add_meta('INFO', items=[
            ('ID', 'PL'),
            ('Number', 1),
            ('Type', 'Integer'),
            ('Description', 'The phred-scaled genotype likelihoods rounded to the closest integer (and otherwise defined precisely as the GL field)')
        ])

        vcfHeader.add_meta('INFO', items=[
            ('ID', 'SCORE'),
            ('Number', 1),
            ('Type', 'Float'),
            ('Description', 'Custom scoring function')
        ])


        for reference in self.fastaFile.references:
            vcfHeader.contigs.add(
                reference,
                self.fastaFile.get_reference_length(reference)
            )

        vcfFile = pysam.VariantFile(outputVfc, mode='w', header=vcfHeader)

        for position in progressBar:
            if self.memory[position]['totalDepth'] >= self.minTotalDepth:
                errorProbabilities = {
                    allele: [
                        from_phred_scale(quality)
                        for quality in self.memory[position]['baseQualities'][allele]
                    ]
                    for allele in self.memory[position]['baseQualities'].keys()
                }

                genotypeLikelihoods = {
                    allele: genotype_likelihood(allele, errorProbabilities)
                    for allele in errorProbabilities.keys()
                }

                sumGenotypeLikelihoods = functools.reduce(operator.add, genotypeLikelihoods.values(), 0.0)
                sumGenotypeLikelihoods = sumGenotypeLikelihoods if sumGenotypeLikelihoods != 0 else 1.0

                variants = []

                for allele in errorProbabilities.keys():
                    evidenceDepth = len(errorProbabilities[allele])

                    filterConstrains = [
                        self.memory[position]['reference'] != allele,
                        evidenceDepth >= self.minEvidenceDepth,
                        evidenceDepth / self.memory[position]['totalDepth'] >= self.minEvidenceRatio
                    ]

                    if all(filterConstrains):
                        genotypeLikelihood = genotypeLikelihoods[allele]

                        if genotypeLikelihood != 0:
                            gl = math.log10(genotypeLikelihood)
                            pl = round(-10.0 * gl)
                        else:
                            gl = 0
                            pl = 0
                        
                        score = to_phred_scale(1.0 - (genotypeLikelihoods[allele] / sumGenotypeLikelihoods))
                        qual = np.mean(errorProbabilities[allele])

                        variants.append({
                            'start': position,
                            'stop': position + 1,
                            'alleles': (
                                self.memory[position]['reference'], 
                                allele
                            ),
                            'qual': qual,
                            'info': {
                                'TD': self.memory[position]['totalDepth'],
                                'ED': evidenceDepth,
                                'GL': gl,
                                'PL': pl,
                                'SCORE': score
                            }
                        })

                for index, variant in enumerate(sorted(variants, key=lambda variant: variant['info']['SCORE'])):
                    if self.maxVariants == 0 or index < self.maxVariants:
                        vcfFile.write(
                            vcfFile.new_record(
                                start=variant['start'], 
                                stop=variant['stop'],
                                alleles=variant['alleles'],
                                qual=variant['qual'],
                                info=variant['info'],
                            )
                        )

        vcfFile.close()
