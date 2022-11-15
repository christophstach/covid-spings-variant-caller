import multiprocessing
import socket
import time
import threading
import daemon
import VCQueue from VCQueue
import logging
import configparser
from variant_caller.live_variant_caller import LiveVariantCaller
from variant_caller.config import minBaseQuality, minMappingQuality, minTotalDepth

logging.basicConfig(filename='vcf_server.log',
                    level=logging.DEBUG,
                    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s')

config = configparser.ConfigParser()
config.read('settings.config')
HOST = config['BASIC_PARAMS']['HOST']
PORT = int(config['BASIC_PARAMS']['PORT'])
queue_size = config['BASIC_PARAMS']['QUEUE_SIZE']

liveVariantCaller = LiveVariantCaller(
    config['VARIANT_CALLER_PARAMS']['REF'],
    minBaseQuality,
    minMappingQuality,
    minTotalDepth,
    int(config['VARIANT_CALLER_PARAMS']['minEvidenceDepth']),
    float(config['VARIANT_CALLER_PARAMS']['minEvidenceRatio']),
    int(config['VARIANT_CALLER_PARAMS']['maxVariants'])
)


def _process_bam(path: str):
    logging.info(f'Processing BAM with path {path}')
    liveVariantCaller.process_bam(path)




def _shutdown_gracefully(sock):
    logging.info('Stopping server in 10 seconds...')
    time.sleep(10)
    sock.shutdown(socket.SHUT_RDWR)
    sock.close()
    return True


def _run():

    #if queue_size < 0:
    try:
        task_queue = VCQueue(queue_size)
    # TODO: Reconsider exception type and size
    except Exception:
        logging.error('Incorrect queue size specified.')

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, PORT))
        sock.listen()
        logging.info(f'Ru v vcnning now under {HOST}:{PORT}...')

        while True:
            connection, address = sock.accept()
            with connection:
                data = connection.recv(1024)
                logging.info(f"Received {data!r}")
                recv_data = data.decode('utf-8').split(' ')

                if recv_data[0] == 'stop':
                    _shutdown_gracefully(sock)
                elif recv_data[0] == 'process' or recv_data[0] == 'write':
                    #_process_bam(recv_data[1])
                    task_queue.put((recv_data[0], recv_data[1]))
                    #print(task_queue.)
                    #_write_vcf(recv_data[1])
                    #print(task_queue)
                else:
                    logging.error(f'No such action: {recv_data[0]}')

                while task_queue.not_empty:
                    task_queue.get()

# with daemon.DaemonContext():
#    logging.info("LOL")
# serve_forever()


if __name__ == '__main__':
    _run()
