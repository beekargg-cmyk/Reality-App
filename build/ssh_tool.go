package main

import (
	"bytes"
	"flag"
	"fmt"
	"io"
	"os"
	"path"
	"strings"

	"golang.org/x/crypto/ssh"
)

func main() {
	host := flag.String("host", "", "Host IP:port")
	user := flag.String("user", "root", "Username")
	pass := flag.String("pass", "", "Password")
	cmd := flag.String("cmd", "", "Command to run")
	uploadSrc := flag.String("upload-src", "", "Local file path to upload")
	uploadDst := flag.String("upload-dst", "", "Remote file path to save to")
	downloadSrc := flag.String("download-src", "", "Remote file path to download")
	downloadDst := flag.String("download-dst", "", "Local file path to save to")

	flag.Parse()

	if *host == "" || *pass == "" {
		fmt.Println("Error: host and pass are required")
		os.Exit(1)
	}

	if !strings.Contains(*host, ":") {
		*host = *host + ":22"
	}

	config := &ssh.ClientConfig{
		User: *user,
		Auth: []ssh.AuthMethod{
			ssh.Password(*pass),
		},
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
	}

	client, err := ssh.Dial("tcp", *host, config)
	if err != nil {
		fmt.Printf("Failed to dial: %s\n", err)
		os.Exit(1)
	}
	defer client.Close()

	if *uploadSrc != "" && *uploadDst != "" {
		err = uploadFile(client, *uploadSrc, *uploadDst)
		if err != nil {
			fmt.Printf("Failed to upload: %s\n", err)
			os.Exit(1)
		}
		fmt.Println("Upload successful")
		return
	}

	if *downloadSrc != "" && *downloadDst != "" {
		err = downloadFile(client, *downloadSrc, *downloadDst)
		if err != nil {
			fmt.Printf("Failed to download: %s\n", err)
			os.Exit(1)
		}
		fmt.Println("Download successful")
		return
	}

	if *cmd != "" {
		session, err := client.NewSession()
		if err != nil {
			fmt.Printf("Failed to create session: %s\n", err)
			os.Exit(1)
		}
		defer session.Close()

		var stdout, stderr bytes.Buffer
		session.Stdout = &stdout
		session.Stderr = &stderr

		err = session.Run(*cmd)
		if err != nil {
			fmt.Printf("Command failed: %s\n", err)
		}
		fmt.Printf("STDOUT:\n%s\n", stdout.String())
		fmt.Printf("STDERR:\n%s\n", stderr.String())
		return
	}

	fmt.Println("Nothing to do. Specify -cmd, -upload-src/-upload-dst, or -download-src/-download-dst")
}

func uploadFile(client *ssh.Client, src, dst string) error {
	session, err := client.NewSession()
	if err != nil {
		return err
	}
	defer session.Close()

	file, err := os.Open(src)
	if err != nil {
		return err
	}
	defer file.Close()

	stat, err := file.Stat()
	if err != nil {
		return err
	}

	w, err := session.StdinPipe()
	if err != nil {
		return err
	}

	err = session.Start(fmt.Sprintf("scp -t %s", path.Dir(dst)))
	if err != nil {
		w.Close()
		return err
	}

	fmt.Fprintf(w, "C0644 %d %s\n", stat.Size(), path.Base(dst))
	_, err = io.Copy(w, file)
	if err != nil {
		w.Close()
		return err
	}
	fmt.Fprint(w, "\x00")
	w.Close()

	return session.Wait()
}

func downloadFile(client *ssh.Client, src, dst string) error {
	session, err := client.NewSession()
	if err != nil {
		return err
	}
	defer session.Close()

	var stdout bytes.Buffer
	session.Stdout = &stdout

	// Simple cat to download file content (works for text/small binary files)
	err = session.Run(fmt.Sprintf("cat %s", src))
	if err != nil {
		return err
	}

	err = os.WriteFile(dst, stdout.Bytes(), 0644)
	return err
}
