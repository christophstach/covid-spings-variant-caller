import numpy as np
import variant_caller.utils as u


if __name__ == '__main__':

    single_site_results = [('A',25),('A',5),('G',11),('C',2)]
    single_site_results = [('C',18),('A',10),('A',5),('G',11)]
    single_site_results = [('G',15),('C',23),('A',3),('A',3),('A',3)]
    
    index_dict = {'A':0,'G':1,'C':2,'T':3}
    
    dist = u.init_prior()
    
    for read in single_site_results:
        dist = u.update_dist(dist, u.get_likelihood(read))
        #print(dist.round(2))
        print((-np.log(dist)/np.log(10)).round(2))
    

    #print(u.compressed_version(single_site_results).round(5))