#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <sys/types.h>
#include <stdlib.h>
#include <iostream>
#include <fstream>
#include <string>
#include <sstream>
#include <errno.h>
#include <netdb.h>
#include <vector>
#include <iomanip>
#include <string.h>
using namespace std;

#define MAX_CLIENTS 20
#define BUFLEN 400000

ssize_t Readline(int sockd, char* vptr, size_t maxlen) {
	ssize_t n, rc;
	char c;
	char* buffer;

	buffer = vptr;

	for (n = 1; n < maxlen; n++) {
		if ((rc = read(sockd, &c, 1)) == 1) {
			*buffer++ = c;
			if (c == '\n')
				break;
		} else if (rc == 0) {
			if (n == 1)
				return 0;
			else
				break;
		} else {
			if (errno == EINTR)
				continue;
			return -1;
		}
	}

	*buffer = 0;
	return n;
}

struct cacheEntry {
	string request;
	string page;
	int len;
};

int main(int argc, char *argv[]) {
	//Verificare numar de argumente
	if (argc != 2) {
		printf("Eroare, numar de argumente gresit!\n");
		exit(-1);
	}

	//Setare port + altele
	unsigned int port_server = atoi(argv[1]);
	struct sockaddr_in serv_addr, cli_addr;
	memset((char *) &serv_addr, 0, sizeof(serv_addr));
	serv_addr.sin_family = AF_INET;
	serv_addr.sin_addr.s_addr = INADDR_ANY;
	serv_addr.sin_port = htons(port_server);

	//Creare socket TCP
	int sockTCP;
	unsigned int clilen;
	sockTCP = socket(AF_INET, SOCK_STREAM, 0);
	if (sockTCP < 0) {
		printf("Eroare la apel socket\n");
		exit(-1);
	}
	if (bind(sockTCP, (struct sockaddr *) &serv_addr, sizeof(struct sockaddr))
			< 0) {
		printf("Eroare la apel bind\n");
		exit(-1);
	}

	//Asculta la portul primit(conexiune TCP)
	listen(sockTCP, MAX_CLIENTS);

	//Multiplexare
	int newsockfd;
	fd_set read_fds;
	fd_set tmp_fds;
	int fdmax;
	FD_ZERO(&read_fds);
	FD_ZERO(&tmp_fds);
	FD_SET(sockTCP, &read_fds);
	fdmax = sockTCP;

	//Creare cache
	vector<cacheEntry> cache;

	//Asteapta o cerere
	tmp_fds = read_fds;
	if (select(fdmax + 1, &tmp_fds, NULL, NULL, NULL) == -1)
		printf("ERROR in select");
	int i;
	fdmax = sockTCP;
	while (1) {
		tmp_fds = read_fds;
		if (select(fdmax + 1, &tmp_fds, NULL, NULL, NULL) == -1)
			printf("ERROR in select");
		for (i = 0; i <= fdmax; i++) {
			if (FD_ISSET(i, &tmp_fds)) {

				if (i == sockTCP) {
					clilen = sizeof(cli_addr);
					if ((newsockfd = accept(sockTCP,
							(struct sockaddr *) &cli_addr, &clilen)) == -1) {
						printf("ERROR in accept");
					} else {
						FD_SET(newsockfd, &read_fds);
						if (newsockfd > fdmax) {
							fdmax = newsockfd;
						}
					}
				} else {

					//Buffer in care se salveaza informatia
					char buffer[BUFLEN];

					//Salvare linia 1 si 2
					char* line1 = new char[BUFLEN];
					char* line2 = new char[BUFLEN];
					string httpRequest("");
					int lenRequest = 0;
					int port;

					//Stringuri folosite pentru comparare
					string myget("GET");
					string mypost("POST");
					string myconnect("CONNECT");

					struct hostent* host;

					//Preluare date de la client
					int j = 0;
					bool stop = false;
					while (stop == false) {
						int nr;
						if (j < 2) {
							nr = Readline(i, buffer, BUFLEN);
							lenRequest = lenRequest + nr;
						} else {
							nr = recv(i, buffer, BUFLEN, 0);
							stop = true;
							lenRequest = lenRequest + nr;
							httpRequest = httpRequest + buffer;
							break;
						}
						j++;
						if (j == 1) {
							memcpy(line1, buffer, BUFLEN);
						}
						if (j == 2) {
							memcpy(line2, buffer, BUFLEN);
						}
						httpRequest = httpRequest + buffer;
					}

					//Verificare existenta in cache
					bool isInCache = false;
					for (int v = 0; v < cache.size(); v++) {
						if (cache[v].request == httpRequest) {
							send(i, cache[v].page.c_str(), cache[v].len, 0);
							isInCache = true;
							close(i);
							FD_CLR(i, &read_fds);
						}
					}

					//Folosit pentru alegere in functie de cele 2 formate
					//pentru cerere
					string dummyChoose(line2);

					string requestCopy = httpRequest;

					if (isInCache == false) {
						if (dummyChoose.find("Host: ") != std::string::npos) {

							//Cazul 1 (format cu Host:)

							string dummyString;
							vector < string > firstLine;
							vector < string > secondLine;
							stringstream myStream(line1);
							stringstream myStream2(line2);
							while (getline(myStream, dummyString, ' ')) {
								firstLine.push_back(dummyString);
							}
							while (getline(myStream2, dummyString, ' ')) {
								secondLine.push_back(dummyString);
							}

							//Verificare cereri gresite
							if (firstLine[0] != myget && firstLine[0] != mypost
									&& firstLine[0] != myconnect) {
								char errormsg[100];
								sprintf(errormsg, "HTTP/1.0 400 BadRequest");
								send(i, errormsg, sizeof(errormsg), 0);
								close(i);
								FD_CLR(i, &read_fds);
								exit(-1);
							}
							if (firstLine[1].find("://") == std::string::npos) {
								char errormsg[100];
								sprintf(errormsg, "HTTP/1.0 400 BadRequest");
								send(i, errormsg, sizeof(errormsg), 0);
								close(i);
								FD_CLR(i, &read_fds);
								exit(-1);
							}

							firstLine[1] = firstLine[1].substr(
									firstLine[1].find("//") + 2);

							//Verificare existenta port si setare port
							if (firstLine[1].find(":") == std::string::npos) {
								port = 80; //port implicit
							} else {
								firstLine[1].substr(firstLine[1].find(":") + 1);
								port = atoi(firstLine[1].c_str());
							}

							//Prelucrare pentru DNS
							secondLine[1].erase(secondLine[1].end() - 1);
							secondLine[1].erase(secondLine[1].end() - 1);
							if (secondLine[1].find("www.")
									!= std::string::npos) {
								secondLine[1] = secondLine[1].substr(4);
							}
							const char* name = secondLine[1].c_str();

							//Aflare adresa IP
							host = gethostbyname(name);
						} else {
							//Cazul 2(format fara Host:)
							vector < string > firstLine;
							stringstream myStream(line1);
							string dummy;
							while (getline(myStream, dummy, ' ')) {
								firstLine.push_back(dummy);
							}
							//Verificare corectitudine cerere
							if (firstLine[0] != myget && firstLine[0] != mypost
									&& firstLine[0] != myconnect) {
								char errormsg[100];
								sprintf(errormsg, "HTTP/1.0 400 BadRequest");
								send(i, errormsg, sizeof(errormsg), 0);
								close(i);
								FD_CLR(i, &read_fds);
								exit(-1);
							}
							if (firstLine[1].find("://") == std::string::npos) {
								char errormsg[100];
								sprintf(errormsg, "HTTP/1.0 400 BadRequest");
								send(i, errormsg, sizeof(errormsg), 0);
								close(i);
								FD_CLR(i, &read_fds);
								exit(-1);
							}

							//Prelucrare pentru DNS
							firstLine[1] = firstLine[1].substr(
									firstLine[1].find("//") + 2);
							string mycopy(firstLine[1]);
							int pos = mycopy.find("/");
							if (pos != std::string::npos) {
								mycopy = mycopy.substr(0, pos);
							}
							const char* name = mycopy.c_str();

							host = gethostbyname(name);

							//Verificare existenta port si setare
							if (firstLine[1].find(":") == std::string::npos) {
								port = 80; //port implicit
							} else {
								firstLine[1].substr(firstLine[1].find(":") + 1);
								port = atoi(firstLine[1].c_str());
							}
						}

						//Verificare existenta host
						if (host == NULL) {
							printf("Eroare host necunoscut\n");
							exit(-1);
						}

						//Aflare adresa ip
						struct in_addr ** addr =
								(struct in_addr**) host->h_addr_list;
						string dummystr(inet_ntoa(*addr[0]));
						const char* ip = dummystr.c_str();

						//Creare socket comunicare Proxy->Server si Server->Proxy
						int sockfd;
						if ((sockfd = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
							printf("Eroare la  creare socket.\n");
							exit(-1);
						}
						struct sockaddr_in servaddr2;
						memset(&servaddr2, 0, sizeof(servaddr2));
						servaddr2.sin_family = AF_INET;
						servaddr2.sin_port = htons(port);
						if (inet_aton(ip, &servaddr2.sin_addr) <= 0) {
							printf("Adresa IP invalida.\n");
							exit(-1);
						}
						if (connect(sockfd, (struct sockaddr *) &servaddr2,
								sizeof(servaddr2)) < 0) {
							printf("Eroare la conectare\n");
							exit(-1);
						}

						//Buffere pentru send si recv cu serverul
						char sendbuf[BUFLEN];
						char recvbuf[4 * BUFLEN];

						httpRequest = httpRequest + "\n\n";

						//Proxy->Server
						send(sockfd, httpRequest.c_str(), lenRequest, 0);
						//Server->Proxy
						int m = recv(sockfd, recvbuf, 4 * BUFLEN, 0);

						//Salvare in cache
						cacheEntry dummyCache;
						dummyCache.request = requestCopy;
						dummyCache.page = recvbuf;
						dummyCache.len = m;
						cache.push_back(dummyCache);

						//Proxy->Client
						send(i, recvbuf, m, 0);

						//Inchidere socketi
						close(sockfd);
						close(i);
						FD_CLR(i, &read_fds);
					}
				}
			}
		}

	}

}